"""Servidor web do Jarvis (FastAPI + WebSocket).

O browser captura o microfone (com selecao de device) e faz streaming de PCM16
16kHz pro backend. Aqui rodamos VAD + Whisper + Claude + voz e devolvemos:
estado, transcricao, resposta e o audio (mp3) — com a esfera vibrando.

CAPTURA MAO-LIVRE (igual EntrevistaAI):
  mic aberto -> WebRTC VAD detecta inicio/fim da fala sozinho -> transcreve ->
  responde. SEM segurar botao, SEM clicar a cada frase. Voce so fala.

  (Existe tambem um modo manual 'segurar para falar' opcional via talk_start/stop,
   util em reuniao barulhenta — mas o padrao e mao-livre.)

Rodar:  python -m uvicorn jarvis.web.server:app --port 8000
"""
import asyncio
import json
import logging
from collections import deque
from pathlib import Path

import numpy as np
import webrtcvad
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import config
from ..voice import stt, tts
from ..core.brain import Jarvis

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger("jarvis.web")

app = FastAPI(title="Jarvis")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

# ── VAD (deteccao de voz, igual EntrevistaAI) ──
VAD_AGGRESSIVENESS = 2          # 0..3 (2 = bom equilibrio sensibilidade x ruido)
VAD_FRAME_MS = 30              # webrtcvad aceita 10/20/30ms
VAD_FRAME_BYTES = int(config.SAMPLE_RATE * 2 * VAD_FRAME_MS / 1000)  # 960 bytes @16k
SILENCE_HANG_MS = 800          # silencio (apos fala) que encerra a frase
MIN_SPEECH_MS = 300            # ignora estalos/ruidos muito curtos
PREROLL_MS = 240               # guarda um tico ANTES da fala p/ nao cortar a 1a silaba
MAX_UTTER_MS = 15000           # trava de seguranca


@app.get("/")
def index():
    return FileResponse(str(STATIC / "index.html"))


def _rms(data: bytes) -> float:
    a = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(a * a))) if a.size else 0.0


class Session:
    def __init__(self):
        self.brain = Jarvis()
        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self.mode = "listen"            # listen (VAD mao-livre) | manual (segurar) | busy
        self.meet_url = None
        self._frames = bytearray()      # acumula bytes p/ fatiar em frames de 30ms
        self._preroll = deque(maxlen=max(1, PREROLL_MS // VAD_FRAME_MS))
        self._reset_utter()
        self.manual_buf = bytearray()

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

    # ── modo manual (botao opcional 'segurar para falar') ──
    def begin_manual(self):
        self.manual_buf = bytearray()
        self.mode = "manual"

    def end_manual(self) -> bytes:
        pcm = bytes(self.manual_buf)
        self.manual_buf = bytearray()
        self.mode = "busy"
        return pcm

    def feed(self, data: bytes):
        """Processa audio do mic. Retorna eventos [(kind, value)]."""
        events = []
        if self.mode == "busy":
            return events
        if self.mode == "manual":
            self.manual_buf.extend(data)
            return events

        # ── mao-livre: VAD fatia a fala sozinho ──
        self._frames.extend(data)
        while len(self._frames) >= VAD_FRAME_BYTES:
            frame = bytes(self._frames[:VAD_FRAME_BYTES])
            del self._frames[:VAD_FRAME_BYTES]
            self._vad_frame(frame, events)
            if self.mode == "busy":      # frase encerrou no meio do lote
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
                # comecou a falar -> abre a frase com o pre-roll p/ nao cortar inicio
                self.utter = bytearray(b"".join(self._preroll))
                self._preroll.clear()
                self.collecting = True
                self.speech_ms = VAD_FRAME_MS
                self.silence_ms = 0
                events.append(("state", "listening"))
            return

        # ja coletando a frase
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
            logger.info("VAD: frase de %.2fs encerrada (silencio).", len(pcm) / 2 / config.SAMPLE_RATE)
            events.append(("capture_done", pcm))

    # Frases que o Whisper "inventa" no silencio.
    _HALLUCINATIONS = {
        "thank you", "thanks for watching", "thank you for watching",
        "obrigado", "obrigada", "you", "bye", "tchau", ".", "",
    }

    @staticmethod
    def _has_speech(pcm: bytes) -> bool:
        # VAD ja garantiu que tem fala; isto so barra captura vazia/curtissima.
        if len(pcm) < int(0.25 * config.SAMPLE_RATE * 2):
            return False
        return _rms(pcm) > 60.0

    def finalize_sync(self, pcm: bytes):
        if not self._has_speech(pcm):
            return None, None, b""
        text = stt.transcribe(pcm)
        clean = text.strip().lower().strip(".!?, ")
        if clean in self._HALLUCINATIONS:
            logger.info("Descartado (alucinacao/silencio): %r", text)
            return None, None, b""
        reply = self.brain.ask(text)
        audio = tts.synthesize(reply)
        return text, reply, audio


async def _handle_capture(ws: WebSocket, sess: Session, pcm: bytes):
    if not pcm or not Session._has_speech(pcm):
        await ws.send_json({"type": "state", "state": "idle"})
        sess.back_to_listen()
        return
    await ws.send_json({"type": "state", "state": "thinking"})
    text, reply, audio = await asyncio.to_thread(sess.finalize_sync, pcm)
    if not text:
        await ws.send_json({"type": "state", "state": "idle"})
        sess.back_to_listen()
        return
    await ws.send_json({"type": "transcript", "text": text})
    await ws.send_json({"type": "reply", "text": reply})
    await ws.send_json({"type": "state", "state": "speaking"})
    if audio:
        await ws.send_bytes(audio)
    else:
        # sem audio -> avisa o cliente p/ voltar a escutar (senao trava mudo)
        await ws.send_json({"type": "state", "state": "idle"})
    sess.back_to_listen()


async def _handle_control(ws: WebSocket, sess: Session, data: dict):
    typ = data.get("type")
    if typ == "talk_start":            # botao opcional 'segurar para falar'
        sess.begin_manual()
        await ws.send_json({"type": "state", "state": "listening"})
    elif typ == "talk_stop":
        if sess.mode == "manual":
            pcm = sess.end_manual()
            logger.info("manual: %.2fs capturados", len(pcm) / 2 / config.SAMPLE_RATE)
            await _handle_capture(ws, sess, pcm)
    elif typ == "set_meet":
        sess.meet_url = data.get("url")
        await ws.send_json({"type": "info", "message": f"Reuniao definida: {data.get('url')}"})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        sess = await asyncio.to_thread(Session)
    except Exception as e:
        logger.exception("Falha ao iniciar sessao")
        await ws.send_json({"type": "error", "message": str(e)})
        await ws.close()
        return

    await ws.send_json({"type": "state", "state": "idle"})
    await ws.send_json({"type": "info", "message": "Jarvis online. Pode falar, senhor — estou ouvindo."})

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
