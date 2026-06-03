"""Jarvis web server (FastAPI + WebSocket).

The browser streams 16 kHz PCM16 microphone audio to the backend. The backend
runs VAD, Whisper, Claude, and TTS, then returns state, transcript, reply text,
and MP3 audio for the orb UI.

Default capture is hands-free: the microphone stays open, WebRTC VAD detects
utterance boundaries, and the backend responds. Optional manual push-to-talk is
available through talk_start/talk_stop for noisy rooms.

Run: python -m uvicorn jarvis.web.server:app --port 8000
"""
import asyncio
import json
import logging
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
import webrtcvad
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import config
from ..voice import stt, tts
from ..core.brain import Jarvis, ROOM_SYSTEM_PROMPT, ROOM_TOOLS
from ..meet.bot import MeetBot

# Logging: console AND a single monitored file. Source-tagged lines:
#   [PC] you / [PC] jarvis        -> your computer microphone (private channel)
#   [ROOM] heard / [jarvis->ROOM] -> the Google Meet audio (room + your meeting mic)
LOG_FILE = config.BASE_DIR / "logs" / "jarvis.log"
LOG_FILE.parent.mkdir(exist_ok=True)
_LOG_FMT = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                             datefmt="%H:%M:%S")
_root = logging.getLogger()
_root.setLevel(logging.INFO)
if not any(getattr(h, "_jarvis", False) for h in _root.handlers):
    for _h in (logging.StreamHandler(), logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")):
        _h.setFormatter(_LOG_FMT)
        _h._jarvis = True
        _root.addHandler(_h)
logging.getLogger("httpx").setLevel(logging.WARNING)  # silence per-request HTTP noise
logger = logging.getLogger("jarvis.web")
logger.info("==================== JARVIS SESSION START ====================")

app = FastAPI(title="Jarvis")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

# VAD
VAD_AGGRESSIVENESS = 2          # 0..3 (2 balances sensitivity and noise).
VAD_FRAME_MS = 30              # webrtcvad accepts 10/20/30ms.
VAD_FRAME_BYTES = int(config.SAMPLE_RATE * 2 * VAD_FRAME_MS / 1000)  # 960 bytes @16k
SILENCE_HANG_MS = 800          # Silence after speech that closes the utterance.
MIN_SPEECH_MS = 300            # Ignore clicks and very short noises.
PREROLL_MS = 240               # Keep audio before speech so the first syllable is not cut.
MAX_UTTER_MS = 15000           # Safety cap.


@app.get("/")
def index():
    return FileResponse(str(STATIC / "index.html"))


def _rms(data: bytes) -> float:
    a = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


def _now_line() -> str:
    """Current local date/time, so Jarvis can answer 'what day is it?'."""
    return "Current date and time (local): " + datetime.now().strftime("%A, %Y-%m-%d %H:%M")


class Session:
    def __init__(self):
        self.brain = Jarvis(
            tool_handler=self._tool_handler,
            context_provider=self._runtime_context,
        )
        # Separate brain for the room: answers participants out loud and may take
        # the minutes (ROOM_TOOLS = notes only). It can NEVER join/leave or touch
        # the mic — those tools are not exposed to it.
        self.room_brain = Jarvis(
            tool_handler=self._tool_handler,
            context_provider=_now_line,
            system_prompt=ROOM_SYSTEM_PROMPT,
            tools=ROOM_TOOLS,
        )
        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self.mode = "listen"            # listen (hands-free VAD) | manual | busy
        self.meet_url = None
        self.bot = None                 # MeetBot (criado sob demanda)
        self.on_event = lambda kind, msg: None  # setado pelo ws_endpoint
        self._frames = bytearray()      # acumula bytes p/ fatiar em frames de 30ms
        self._preroll = deque(maxlen=max(1, PREROLL_MS // VAD_FRAME_MS))
        self._reset_utter()
        self.manual_buf = bytearray()

    def _runtime_context(self) -> str:
        bot_exists = self.bot is not None
        bot_running = bool(bot_exists and getattr(self.bot, "_running", False))
        in_call = bool(bot_exists and getattr(self.bot, "in_call", False))
        notes_active = bool(bot_exists and getattr(self.bot.notes, "active", False))
        mic_muted = bool(getattr(self.bot, "mic_muted", True)) if bot_exists else True
        return (
            _now_line() + "\n"
            f"meet_url={self.meet_url or ''}\n"
            f"meet_bot_exists={bot_exists}\n"
            f"meet_bot_running={bot_running}\n"
            f"meet_in_call={in_call}\n"
            f"meet_mic_muted={mic_muted}\n"
            f"meeting_notes_active={notes_active}"
        )

    # Google Meet bot.
    def _get_bot(self) -> MeetBot:
        if self.bot is None:
            self.bot = MeetBot(on_event=lambda kind, msg: self.on_event(kind, msg))
            self.bot.start()
        return self.bot

    def _join_and_announce(self, url: str, intro_text: str) -> str:
        url = (url or "").strip() or self.meet_url
        if not url:
            return "No meeting URL was provided. Ask the user to paste the Meet link."

        intro_text = (intro_text or config.MEET_DEFAULT_INTRO).strip()
        self.meet_url = url
        bot = self._get_bot()

        ok, join_val = bot.join(url)
        if not ok or not bot.in_call:
            return f"I could not confirm that I joined the meeting: {join_val}"

        self.on_event("meet", "Speaking to the room: " + intro_text)
        mp3 = tts.synthesize(intro_text)
        if not mp3:
            return "I joined the meeting, but could not generate the introduction voice."

        speak_ok, speak_val = bot.speak(mp3)
        if not speak_ok or speak_val != "spoke in the meeting":
            return f"I joined the meeting, but could not speak to the room: {speak_val}"

        return "I joined the meeting and spoke to the room."

    def _join_announce_and_take_notes(self, url: str, intro_text: str) -> str:
        announce_val = self._join_and_announce(url, intro_text)
        if announce_val != "I joined the meeting and spoke to the room.":
            return announce_val

        bot = self._get_bot()
        notes_ok, notes_val = bot.start_notes()
        self.on_event("meet", "Started taking meeting notes.")
        if not notes_ok:
            return f"I spoke to the room, but could not start note taking: {notes_val}"

        return "I joined the meeting, addressed the room, and started taking notes."

    def _tool_handler(self, name: str, inp: dict) -> str:
        """Execute Claude tools against MeetBot from the brain thread."""
        logger.info("TOOL %s inp=%s (meet_url=%s)", name, inp, self.meet_url)
        if name == "get_meeting_status":
            return self._runtime_context()
        bot = self._get_bot()
        if name == "join_and_announce":
            return self._join_and_announce(
                inp.get("url") or "",
                inp.get("intro_text") or config.MEET_DEFAULT_INTRO,
            )
        if name == "join_announce_and_take_notes":
            return self._join_announce_and_take_notes(
                inp.get("url") or "",
                inp.get("intro_text") or config.MEET_DEFAULT_INTRO,
            )
        if name == "join_meeting":
            url = (inp.get("url") or "").strip() or self.meet_url
            if not url:
                return "No meeting URL was provided. Ask the user to paste the Meet link."
            self.meet_url = url
            ok, val = bot.join(url)
            return val
        if name == "speak_to_meeting":
            text = (inp.get("text") or "").strip()
            if not text:
                return "nothing to say"
            self.on_event("meet", "Speaking to the room: " + text)
            mp3 = tts.synthesize(text)
            if not mp3:
                return "I could not generate the voice, so I did not speak to the room."
            ok, val = bot.speak(mp3)
            return val
        if name == "set_meeting_mic":
            ok, val = bot.set_mic(bool(inp.get("muted", True)))
            return val
        if name == "start_taking_notes":
            ok, val = bot.start_notes()
            self.on_event("meet", "Started taking meeting notes.")
            return val
        if name == "stop_taking_notes":
            ok, val = bot.stop_notes()
            return val
        if name == "send_notes_to_chat":
            summary = bot.notes.summary()
            ok, val = bot.post_chat(summary)
            self.on_event("meet", "Meeting notes posted to chat:\n" + summary)
            return f"{val}. Summary:\n{summary}"
        if name == "leave_meeting":
            ok, val = bot.leave()
            return val
        return f"unknown tool: {name}"

    def handle_meeting_command_sync(self, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return "empty meeting command"
        bot = self._get_bot()
        if not bot.in_call:
            return "meeting command ignored because the bot is not in the meeting"

        logger.info("[ROOM->jarvis] command: %s", text)
        reply = self.room_brain.ask(text)   # tool-less: only answers the room
        if not reply:
            return "no reply generated"
        logger.info("[jarvis->ROOM] %s", reply)

        mp3 = tts.synthesize(reply)
        if not mp3:
            return "reply generated, but TTS failed"

        self.on_event("meet", "Replied to the room: " + reply)
        ok, val = bot.speak(mp3)
        return val

    def _reset_utter(self):
        self.collecting = False
        self.utter = bytearray()
        self.speech_ms = 0
        self.silence_ms = 0

    def back_to_listen(self):
        self._frames.clear()
        self._preroll.clear()
        self._reset_utter()
        self.manual_buf = bytearray()
        self.mode = "listen"

    # Optional manual push-to-talk mode.
    def begin_manual(self):
        self.manual_buf = bytearray()
        self.mode = "manual"

    def end_manual(self) -> bytes:
        pcm = bytes(self.manual_buf)
        self.manual_buf = bytearray()
        self.mode = "busy"
        return pcm

    def feed(self, data: bytes):
        """Process microphone audio. Returns events as [(kind, value)]."""
        events = []
        if self.mode == "busy":
            return events
        if self.mode == "manual":
            self.manual_buf.extend(data)
            return events

        # Hands-free mode: VAD segments speech automatically.
        self._frames.extend(data)
        while len(self._frames) >= VAD_FRAME_BYTES:
            frame = bytes(self._frames[:VAD_FRAME_BYTES])
            del self._frames[:VAD_FRAME_BYTES]
            self._vad_frame(frame, events)
            if self.mode == "busy":      # The utterance ended in the middle of this batch.
                self._frames.clear()
                break
        return events

    def _vad_frame(self, frame: bytes, events: list):
        try:
            is_speech = self.vad.is_speech(frame, config.SAMPLE_RATE)
        except Exception:
            is_speech = False

        if not self.collecting:
            self._preroll.append(frame)
            if is_speech:
                # Speech started; prepend preroll so the beginning is not cut.
                self.utter = bytearray(b"".join(self._preroll))
                self._preroll.clear()
                self.collecting = True
                self.speech_ms = VAD_FRAME_MS
                self.silence_ms = 0
                events.append(("state", "listening"))
            return

        # Already collecting the utterance.
        self.utter.extend(frame)
        if is_speech:
            self.speech_ms += VAD_FRAME_MS
            self.silence_ms = 0
        else:
            self.silence_ms += VAD_FRAME_MS

        total_ms = (len(self.utter) / 2) / config.SAMPLE_RATE * 1000
        ended = self.silence_ms >= SILENCE_HANG_MS and self.speech_ms >= MIN_SPEECH_MS
        too_long = total_ms >= MAX_UTTER_MS
        if ended or too_long:
            pcm = bytes(self.utter)
            self.mode = "busy"
            self._reset_utter()
            self._preroll.clear()
            logger.info("VAD: %.2fs utterance ended by silence.", len(pcm) / 2 / config.SAMPLE_RATE)
            events.append(("capture_done", pcm))

    # Phrases Whisper may hallucinate during silence.
    _HALLUCINATIONS = {
        "thank you", "thanks for watching", "thank you for watching",
        "obrigado", "obrigada", "you", "bye", "tchau", ".", "",
    }

    @staticmethod
    def _has_speech(pcm: bytes) -> bool:
        # VAD already found speech; this only blocks empty or very short captures.
        if len(pcm) < int(0.25 * config.SAMPLE_RATE * 2):
            return False
        return _rms(pcm) > 60.0

    def finalize_sync(self, pcm: bytes):
        if not self._has_speech(pcm):
            return None, None, b""
        text = stt.transcribe(pcm)
        clean = text.strip().lower().strip(".!?, ")
        if clean in self._HALLUCINATIONS:
            logger.info("[PC] discarded hallucination/silence: %r", text)
            return None, None, b""
        logger.info("[PC] you: %s", text)
        reply = self.brain.ask(text)
        logger.info("[PC] jarvis: %s", reply)
        audio = tts.synthesize(reply)
        return text, reply, audio


async def _handle_capture(ws: WebSocket, sess: Session, pcm: bytes):
    # back_to_listen MUST always run, even on error, or the session stays stuck
    # in "busy" and the computer mic goes deaf for the rest of the call.
    try:
        if not pcm or not Session._has_speech(pcm):
            await ws.send_json({"type": "state", "state": "idle"})
            return
        await ws.send_json({"type": "state", "state": "thinking"})
        text, reply, audio = await asyncio.to_thread(sess.finalize_sync, pcm)
        if not text:
            await ws.send_json({"type": "state", "state": "idle"})
            return
        await ws.send_json({"type": "transcript", "text": text})
        await ws.send_json({"type": "reply", "text": reply})
        await ws.send_json({"type": "state", "state": "speaking"})
        if audio:
            await ws.send_bytes(audio)
        else:
            # No audio: tell the client to listen again so it does not stay silent.
            await ws.send_json({"type": "state", "state": "idle"})
    finally:
        sess.back_to_listen()


async def _handle_control(ws: WebSocket, sess: Session, data: dict):
    typ = data.get("type")
    if typ == "talk_start":            # Optional push-to-talk start.
        sess.begin_manual()
        await ws.send_json({"type": "state", "state": "listening"})
    elif typ == "talk_stop":
        if sess.mode == "manual":
            pcm = sess.end_manual()
            logger.info("manual: captured %.2fs", len(pcm) / 2 / config.SAMPLE_RATE)
            await _handle_capture(ws, sess, pcm)
    elif typ == "set_meet":
        sess.meet_url = data.get("url")
        await ws.send_json({"type": "info", "message": f"Meeting URL set: {data.get('url')}"})
    elif typ == "join_meet":
        # UI button only REGISTERS the link. Jarvis joins (and introduces himself
        # once) when the user asks by voice, e.g. "Jarvis, enter the meeting".
        # This avoids a second introduction from a button-triggered join.
        url = (data.get("url") or "").strip()
        if not url:
            await ws.send_json({"type": "meet", "text": "Paste the Meet link first."})
            return
        sess.meet_url = url
        await ws.send_json({
            "type": "meet",
            "text": "Link saved. Say “Jarvis, enter the meeting” and admit him when prompted.",
        })


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        sess = await asyncio.to_thread(Session)
    except Exception as e:
        logger.exception("Failed to start session")
        await ws.send_json({"type": "error", "message": str(e)})
        await ws.close()
        return

    # canal de eventos do MeetBot (outra thread) -> WebSocket
    loop = asyncio.get_running_loop()
    event_q: asyncio.Queue = asyncio.Queue()
    sess.on_event = lambda kind, msg: loop.call_soon_threadsafe(
        event_q.put_nowait, (kind, msg))

    async def drain_events():
        while True:
            kind, msg = await event_q.get()
            try:
                if kind == "note":
                    await ws.send_json({"type": "note", "text": msg})
                elif kind == "meeting_command":
                    await ws.send_json({"type": "meet", "text": "Meeting command: " + msg})

                    async def _reply_to_meeting(command: str):
                        val = await asyncio.to_thread(sess.handle_meeting_command_sync, command)
                        await ws.send_json({"type": "meet", "text": "Meeting reply: " + str(val)})

                    asyncio.create_task(_reply_to_meeting(msg))
                elif kind == "meet":
                    await ws.send_json({"type": "meet", "text": msg})
                elif kind == "error":
                    await ws.send_json({"type": "error", "message": msg})
                else:
                    await ws.send_json({"type": "info", "message": msg})
            except Exception:
                break

    drainer = asyncio.create_task(drain_events())

    await ws.send_json({"type": "state", "state": "idle"})
    await ws.send_json({"type": "info", "message": "Jarvis online. You may speak, sir — I am listening."})

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                for kind, val in sess.feed(msg["bytes"]):
                    if kind == "state":
                        await ws.send_json({"type": "state", "state": val})
                    elif kind == "capture_done":
                        await _handle_capture(ws, sess, val)
            elif msg.get("text") is not None:
                await _handle_control(ws, sess, json.loads(msg["text"]))
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Erro no WebSocket")
    finally:
        drainer.cancel()
