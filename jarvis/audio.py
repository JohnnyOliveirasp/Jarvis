"""Captura de microfone — UM stream continuo.

Acorda na wake word e, SEM fechar o stream, ja captura o comando colado
(ex: "Hey Jarvis, tell me about yourself" dito de uma vez). Um bip local
instantaneo confirma a ativacao sem falar por cima do usuario.
"""
import collections
import logging

import numpy as np
import sounddevice as sd
import webrtcvad

from . import config

logger = logging.getLogger(__name__)

_oww_model = None

# Bip de "pronto" (2 tons curtos) gerado uma vez, tocado localmente.
_BEEP = None


def _get_wake_model():
    global _oww_model
    if _oww_model is not None:
        return _oww_model
    from openwakeword.model import Model
    try:
        _oww_model = Model(wakeword_models=[config.WAKE_WORD], inference_framework="onnx")
    except Exception:
        import openwakeword.utils
        openwakeword.utils.download_models()
        _oww_model = Model(wakeword_models=[config.WAKE_WORD], inference_framework="onnx")
    return _oww_model


def _beep():
    """Toca um bip curto local (instantaneo, sem API)."""
    global _BEEP
    if _BEEP is None:
        sr = config.SAMPLE_RATE
        dur = 0.12
        t = np.linspace(0, dur, int(sr * dur), False)
        tone = 0.25 * np.sin(2 * np.pi * 880 * t)
        # fade in/out p/ nao estalar
        fade = int(sr * 0.01)
        tone[:fade] *= np.linspace(0, 1, fade)
        tone[-fade:] *= np.linspace(1, 0, fade)
        _BEEP = tone.astype(np.float32)
    try:
        sd.play(_BEEP, config.SAMPLE_RATE)
        sd.wait()
    except Exception as e:
        logger.debug("beep falhou: %s", e)


def listen_and_capture() -> bytes:
    """Espera a wake word e captura o comando NO MESMO stream. Retorna PCM16."""
    oww = _get_wake_model()
    oww.reset()
    vad = webrtcvad.Vad(config.VAD_AGGRESSIVENESS)

    frame_cmd = int(config.SAMPLE_RATE * 30 / 1000)          # 480 amostras (30ms)
    silence_limit = int(config.SILENCE_MS_TO_STOP / 30)
    start_timeout = int(config.START_TIMEOUT_MS / 30)
    max_frames = int(config.MAX_COMMAND_SECONDS * 1000 / 30)

    with sd.InputStream(
        samplerate=config.SAMPLE_RATE, channels=1, dtype="int16"
    ) as stream:
        # ── Fase 1: espera a wake word ──
        logger.info("Aguardando wake word '%s'...", config.WAKE_WORD)
        while True:
            arr, _ = stream.read(config.FRAME_SAMPLES)        # 1280 (80ms)
            scores = oww.predict(arr[:, 0])
            if any(v >= config.WAKE_THRESHOLD for v in scores.values()):
                logger.info("Wake word detectada (%s)",
                            {k: round(v, 2) for k, v in scores.items()})
                break

        # ── Bip instantaneo (no mesmo instante; nao fala por cima) ──
        _beep()

        # ── Fase 2: captura o comando no MESMO stream ──
        collected = bytearray()
        ring = collections.deque(maxlen=silence_limit)
        started = False
        n = 0
        while n < max_frames:
            arr, _ = stream.read(frame_cmd)
            pcm = arr[:, 0].tobytes()
            is_speech = vad.is_speech(pcm, config.SAMPLE_RATE)

            if not started:
                if is_speech:
                    started = True
                    collected.extend(pcm)
                    ring.append(True)
                elif n > start_timeout:
                    logger.info("Ninguem falou apos a wake word.")
                    break
            else:
                collected.extend(pcm)
                ring.append(is_speech)
                if len(ring) == ring.maxlen and not any(ring):
                    break
            n += 1

    secs = len(collected) / 2 / config.SAMPLE_RATE
    logger.info("Comando capturado: %.1fs", secs)
    return bytes(collected)
