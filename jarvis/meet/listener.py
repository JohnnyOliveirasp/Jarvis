"""Escuta os PARTICIPANTES da reuniao (pra ata) — sem loopback do Windows.

Estrategia do Vexa (a mais robusta, ver memoria reference-meet-bot-research):
em vez de capturar o audio do sistema (que pegaria a propria voz do Jarvis),
"grampeamos" os elementos <audio>/<video> do Meet DENTRO do browser, via
WebAudio, reamostrando pra 16 kHz, e mandamos os chunks pro Python por um
binding exposto. Aqui o Python segmenta por VAD (igual ao servidor) e transcreve.

Fluxo:
  JS_TAP (injetado na pagina) -> window.__jarvisAudio(base64 PCM16 16k)
    -> MeetListener.feed(pcm) -> webrtcvad fatia a frase
    -> Whisper transcreve numa thread -> MeetingNotes.add_line + on_line()
"""
import base64
import difflib
import logging
import queue
import re
import threading
import time

import numpy as np
import webrtcvad

from .. import config
from ..voice import stt

logger = logging.getLogger(__name__)

# JS injetado no Meet. Conecta cada <audio>/<video> a um ScriptProcessor,
# reamostra pra 16k, junta ~250ms e manda base64 pro binding __jarvisAudio.
# Importante: NAO toca de volta nos alto-falantes (ganho zero) p/ nao duplicar.
JS_TAP = r"""
() => {
  if (window.__jarvisTapStarted) return;
  window.__jarvisTapStarted = true;
  const SR = 16000;
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const sink = ctx.createGain(); sink.gain.value = 0; sink.connect(ctx.destination);
  const tapped = new WeakSet();
  function tap(el) {
    try {
      if (tapped.has(el)) return;
      const ms = el.srcObject || (el.captureStream && el.captureStream());
      if (!ms || !ms.getAudioTracks || ms.getAudioTracks().length === 0) return;
      tapped.add(el);
      const src = ctx.createMediaStreamSource(ms);
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      let buf = [];
      proc.onaudioprocess = (e) => {
        const inp = e.inputBuffer.getChannelData(0);
        const ratio = ctx.sampleRate / SR;
        const outLen = Math.floor(inp.length / ratio);
        const out = new Int16Array(outLen);
        for (let i = 0; i < outLen; i++) {
          let s = inp[Math.floor(i * ratio)];
          s = Math.max(-1, Math.min(1, s));
          out[i] = s < 0 ? s * 32768 : s * 32767;
        }
        buf.push(out);
        let total = 0; for (const b of buf) total += b.length;
        if (total >= SR * 0.25) {
          const merged = new Int16Array(total);
          let o = 0; for (const b of buf) { merged.set(b, o); o += b.length; }
          buf = [];
          const bytes = new Uint8Array(merged.buffer);
          let bin = ''; for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
          if (window.__jarvisAudio) window.__jarvisAudio(btoa(bin));
        }
      };
      src.connect(proc); proc.connect(sink);
    } catch (err) { /* ignora elementos sem stream */ }
  }
  function scan() { document.querySelectorAll('audio, video').forEach(tap); }
  setInterval(scan, 1000); scan();
}
"""

# JS injetado pra LER as legendas (CC) do Google Meet — o Google ja transcreve,
# entao pegamos texto limpo (resolve "drivers" no lugar de "Jarvis"). Cada bloco
# de legenda tem nome do falante + texto. Emitimos uma linha quando o texto fica
# ESTAVEL por ~1s (frase terminou), evitando mandar versoes parciais repetidas.
# Seletores (fragiles, do Meet): container dsyhDe, texto tgaKEf, falante KcIKyf jxFHg.
JS_CAPTIONS = r"""
() => {
  if (window.__jarvisCaptionStarted) return;
  window.__jarvisCaptionStarted = true;
  const recent = [];                         // ultimas linhas emitidas (dedup)
  const stable = {};                         // key -> {text, since}
  function container() {
    return document.querySelector('div[jsname="dsyhDe"]')
        || document.querySelector('[role="region"][aria-label*="aption" i]')
        || document.querySelector('[role="region"][aria-label*="egenda" i]');
  }
  function collect() {
    const c = container();
    if (!c) return [];
    const out = [];
    const texts = c.querySelectorAll('div[jsname="tgaKEf"]');
    const els = texts.length ? texts : c.querySelectorAll('div');
    els.forEach((tEl, i) => {
      const spans = tEl.querySelectorAll('span');
      const text = (spans.length
        ? Array.from(spans).map(s => s.innerText.trim()).filter(Boolean).join(' ')
        : (tEl.innerText || '')).trim();
      if (!text || text.length < 2) return;
      let sp = '', node = tEl;
      for (let k = 0; k < 4 && node; k++) {
        const e = node.querySelector && node.querySelector('div.KcIKyf.jxFHg');
        if (e) { sp = (e.innerText || '').trim(); break; }
        node = node.parentElement;
      }
      out.push({ key: (sp || 'spk') + '#' + i, speaker: sp, text });
    });
    return out;
  }
  setInterval(() => {
    const now = Date.now();
    collect().forEach(r => {
      const s = stable[r.key];
      if (!s || s.text !== r.text) { stable[r.key] = { text: r.text, since: now }; return; }
      // texto estavel ha >=900ms -> frase terminou; emite uma vez.
      if (now - s.since >= 900) {
        const tag = (r.speaker || '') + '|' + r.text;
        if (recent.includes(tag)) return;
        recent.push(tag); if (recent.length > 30) recent.shift();
        if (window.__jarvisCaption) window.__jarvisCaption(r.speaker || '', r.text);
      }
    });
  }, 350);
}
"""

# Parametros de VAD (espelham o servidor web)
_VAD_FRAME_MS = 30
_FRAME_BYTES = int(config.SAMPLE_RATE * 2 * _VAD_FRAME_MS / 1000)
_SILENCE_HANG_MS = 800
_MIN_SPEECH_MS = 400
_MAX_UTTER_MS = 20000

_HALLUC = {"thank you", "thanks for watching", "obrigado", "obrigada",
           "you", "bye", "tchau", ".", ""}


class MeetListener:
    """Receive meeting PCM16 16 kHz audio, segment it with VAD, and transcribe it."""

    def __init__(self, notes, on_line=None, on_command=None):
        self._notes = notes
        self._on_line = on_line
        self._on_command = on_command
        self._vad = webrtcvad.Vad(2)
        self._frames = bytearray()
        self._utter = bytearray()
        self._speech_ms = 0
        self._silence_ms = 0
        self._collecting = False
        self._q: queue.Queue = queue.Queue()
        self._running = False
        self._suspended = False
        self._awaiting_until = 0.0   # follow-up window after a bare "Jarvis"
        self._cap_last = {}          # speaker -> last full caption text (for deltas)
        self._cap_ignore_until = 0.0  # absorb (don't fire) captions until this time
        self._worker = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(target=self._transcribe_loop, daemon=True)
        self._worker.start()

    def stop(self):
        self._running = False

    def suspend(self):
        """Stop ingesting audio (used while Jarvis speaks, to ignore his echo)."""
        self._suspended = True
        self._frames = bytearray()
        self._utter = bytearray()
        self._collecting = False
        self._speech_ms = self._silence_ms = 0
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass

    def resume(self):
        self._suspended = False

    def mute_captions(self, seconds: float):
        """Absorb (track but don't fire/note) captions for `seconds` from now.

        Google captions arrive with a delay, so the lines Jarvis "said" — and any
        echo of his voice captioned as the owner — keep landing a few seconds AFTER
        he stops speaking. During this window we still update the per-speaker
        baseline (_cap_last) so the text doesn't later resurface as a fresh delta,
        but we never turn it into a command or a minute. Kills the self-loop tail.
        (suspend() already covers the actual speaking; this is the trailing tail.)
        """
        self._cap_ignore_until = time.monotonic() + max(0.0, seconds)

    def feed_b64(self, b64: str):
        """Called by the browser binding with base64 PCM16 16 kHz audio."""
        try:
            self.feed(base64.b64decode(b64))
        except Exception as e:
            logger.debug("feed_b64 falhou: %s", e)

    # Google labels the bot's OWN captions (from its own browser) as "You"/"Você".
    # We must never react to those, or Jarvis answers himself in an endless loop.
    _SELF_SPEAKERS = {"you", "voce", "você"}

    # Note-control phrases the OWNER may say WITHOUT the wake word. Kept specific
    # to avoid firing on normal talk (e.g. NOT bare "minutes" -> "two minutes").
    _NOTE_CMD_HINTS = (
        "take note", "taking note", "take the note", "start note", "start taking",
        "begin note", "begin taking", "stop note", "stop taking", "pause note",
        "stop the note", "send note", "send the note", "post note",
        "note to the chat", "notes to the chat", "summarize", "summarise",
        "summary of", "meeting minutes", "the minutes",
        "anota", "anote", "anotar", "faz a ata", "fazer a ata", "comeca a ata",
        "começa a ata", "comece a ata", "iniciar a ata", "parar a ata",
        "para a ata", "pare de anotar", "resuma", "resumo da", "resumir",
        "manda a ata", "manda no chat", "envia a ata",
    )

    def _is_owner(self, speaker: str) -> bool:
        owner = (config.MEET_OWNER_NAME or "").strip().lower()
        return bool(owner) and owner in (speaker or "").lower()

    def _is_note_command(self, text: str) -> bool:
        t = (text or "").lower()
        return any(h in t for h in self._NOTE_CMD_HINTS)

    def feed_caption(self, speaker: str, text: str):
        """Called by the browser binding with a finalized Google Meet caption line.

        Captions are already transcribed by Google (clean text). No audio/VAD/
        Whisper here — we detect the wake word and feed the minutes.
        """
        text = (text or "").strip()
        speaker = (speaker or "").strip()
        if not text:
            return
        spk = speaker.lower()
        bot_name = (config.MEET_BOT_DISPLAY_NAME or "").strip().lower()
        if spk in self._SELF_SPEAKERS or (bot_name and bot_name in spk):
            return  # Jarvis's own voice — ignore (kills the self-trigger loop)

        # Meet keeps GROWING one caption block per speaker; work only on the NEW
        # tail so a growing line never re-fires the same request or duplicates notes.
        key = speaker or "spk"
        prev = self._cap_last.get(key, "")
        delta = text[len(prev):].strip() if (prev and text.startswith(prev)) else text
        # ALWAYS advance the baseline, even while muted — so captions that grow
        # during/just-after Jarvis speaks are absorbed here and never resurface as
        # a "new" delta once we resume. This is what stops the post-speech burst.
        self._cap_last[key] = text
        if self._suspended or time.monotonic() < self._cap_ignore_until:
            return  # speaking / echo cooldown: track only, never fire or note
        if not delta:
            return

        notes_on = getattr(self._notes, "active", False)
        logger.info("[ROOM cap]%s %s: %s", " (notes)" if notes_on else "", speaker or "?", delta)

        # Fire a command only when the wake word is in the NEW part (no re-trigger
        # as the block grows). Pass the FULL line so Jarvis gets the whole request,
        # even if the name was said at the end.
        wake = (config.MEET_WAKE_NAME or "jarvis").strip().lower()
        if self._find_wake(re.findall(r"\w+", delta.lower()), wake) >= 0:
            self._maybe_command(text, speaker)
        elif time.monotonic() < self._awaiting_until:
            self._maybe_command(delta, speaker)
        elif self._is_owner(speaker) and (
            self._is_note_command(delta)
            or (config.MEET_OWNER_OPEN and self._looks_addressed(delta))
        ):
            # The owner can drive notes AND ask questions without the wake name.
            logger.info("owner addressed (no wake) from %r: %r", speaker, delta)
            self._fire(text, speaker)

        # Minutes: store only the new part, and never the bot's own lines.
        if notes_on:
            line = f"{speaker}: {delta}" if speaker else delta
            self._notes.add_line(line)
            if self._on_line:
                try:
                    self._on_line(line)
                except Exception:
                    pass

    def feed(self, pcm: bytes):
        if not self._running or self._suspended:
            return
        self._frames.extend(pcm)
        while len(self._frames) >= _FRAME_BYTES:
            frame = bytes(self._frames[:_FRAME_BYTES])
            del self._frames[:_FRAME_BYTES]
            self._vad_frame(frame)

    def _vad_frame(self, frame: bytes):
        try:
            is_speech = self._vad.is_speech(frame, config.SAMPLE_RATE)
        except Exception:
            is_speech = False

        if not self._collecting:
            if is_speech:
                self._utter = bytearray(frame)
                self._collecting = True
                self._speech_ms = _VAD_FRAME_MS
                self._silence_ms = 0
            return

        self._utter.extend(frame)
        if is_speech:
            self._speech_ms += _VAD_FRAME_MS
            self._silence_ms = 0
        else:
            self._silence_ms += _VAD_FRAME_MS

        total_ms = (len(self._utter) / 2) / config.SAMPLE_RATE * 1000
        ended = self._silence_ms >= _SILENCE_HANG_MS and self._speech_ms >= _MIN_SPEECH_MS
        if ended or total_ms >= _MAX_UTTER_MS:
            self._q.put(bytes(self._utter))
            self._utter = bytearray()
            self._collecting = False
            self._speech_ms = self._silence_ms = 0

    @staticmethod
    def _rms(pcm: bytes) -> float:
        a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(a * a))) if a.size else 0.0

    @staticmethod
    def _is_garbage(text: str) -> bool:
        """Reject Whisper noise: too repetitive or letter-by-letter spelling."""
        words = re.findall(r"\w+", text.lower())
        if len(words) >= 6:
            uniq = len(set(words)) / len(words)
            if uniq < 0.45:                      # same word over and over
                return True
            singles = sum(1 for w in words if len(w) == 1)
            if singles / len(words) > 0.4:       # "S U T T H A T O O ..." spelling
                return True
        return False

    def _transcribe_loop(self):
        while self._running:
            try:
                pcm = self._q.get(timeout=0.3)
            except queue.Empty:
                continue
            if self._suspended:
                continue
            if self._rms(pcm) < 120.0:           # too quiet -> silence/echo tail
                continue
            text = stt.transcribe(pcm)
            clean = text.strip().lower().strip(".!?, ")
            if not clean or clean in _HALLUC or self._is_garbage(text):
                logger.debug("[ROOM] dropped noise/garbage: %r", text)
                continue
            notes_on = getattr(self._notes, "active", False)
            logger.info("[ROOM] heard%s: %s", " (notes on)" if notes_on else "", text)
            # The room may address Jarvis by name at any time, notes or not.
            self._maybe_command(text)
            # Minutes are only recorded and shown while note taking is active.
            if getattr(self._notes, "active", False):
                self._notes.add_line(text)
                if self._on_line:
                    try:
                        self._on_line(text)
                    except Exception:
                        pass

    # Common ways Whisper mishears "Jarvis" (PT/EN accents, noisy rooms).
    # NOTE: do NOT add real common words (e.g. "drivers") here — they cause false
    # wake triggers on normal speech. Keep only close, uncommon mishears.
    _WAKE_MISHEARS = {
        "jarvis", "jarvas", "jarves", "jarvix", "jarviz", "jervis", "jervais",
        "jorves", "jorvis", "jarbis", "jarvys", "jarviss",
    }

    # Question/request openers — for the OWNER's open mode (answer without "Jarvis").
    _ADDRESS_HINTS = (
        # questions
        "what", "how", "why", "when", "who", "where", "which", "can you",
        "could you", "do you", "would you", "tell me", "explain", "give me",
        "is it", "are you",
        "que", "qual", "quais", "quando", "como", "por que", "porque", "quem",
        "onde", "pode", "poderia", "me diga", "me diz", "explica", "explique",
        "fala", "diz", "voce pode", "você pode",
        # imperatives addressed to the assistant (camera/mic/notes/leave/chat)
        "turn on", "turn off", "mute", "unmute", "show yourself", "hide", "leave",
        "send", "start", "stop", "take note", "post", "summari",
        "liga", "ligar", "desliga", "desligar", "mostre", "mostra", "esconde",
        "muta", "silencia", "sai", "manda", "envie", "envia", "anota", "resume",
    )

    def _looks_addressed(self, text: str) -> bool:
        t = (text or "").strip().lower()
        if t.endswith("?"):
            return True
        return any(t.startswith(w) or (" " + w + " ") in (" " + t + " ")
                   for w in self._ADDRESS_HINTS)

    def _find_wake(self, words: list, wake: str):
        """Return the index of the word that matches the wake name, or -1.

        Matches exact, known mishears, or anything phonetically close (so
        "Jorves"/"Jarvas" still wake Jarvis without firing on random words).
        """
        for i, w in enumerate(words):
            if w == wake or w in self._WAKE_MISHEARS:
                return i
            if difflib.SequenceMatcher(None, w, wake).ratio() >= 0.7:
                return i
        return -1

    def _fire(self, command: str, speaker: str = ""):
        is_owner = self._is_owner(speaker)
        logger.info("room command (owner=%s) -> %r", is_owner, command)
        try:
            self._on_command(command, is_owner)
        except Exception:
            logger.exception("meeting command callback failed")

    def _maybe_command(self, text: str, speaker: str = ""):
        if not self._on_command:
            return
        raw = (text or "").strip()
        if not raw:
            return
        now = time.monotonic()
        # Follow-up window: the previous utterance was a bare "Jarvis"; take this
        # whole utterance as the command, no need to repeat the name.
        if now < self._awaiting_until:
            self._awaiting_until = 0.0
            self._fire(raw, speaker)
            return
        wake = (config.MEET_WAKE_NAME or "jarvis").strip().lower()
        # Split keeping positions so we can recover the text after the wake word.
        tokens = list(re.finditer(r"\w+", raw.lower()))
        words = [m.group(0) for m in tokens]
        hit = self._find_wake(words, wake)
        if hit < 0:
            return
        after = raw[tokens[hit].end():].strip(" .,:;!?-")
        if after:
            logger.info("room wake matched on %r", words[hit])
            self._fire(after)
        else:
            # Bare "Jarvis": open a short window so the next sentence is the command.
            logger.info("room wake (bare) on %r -> awaiting follow-up", words[hit])
            self._awaiting_until = now + 6.0
            self._fire(raw)
