"""Voz do Jarvis (ElevenLabs, clone da voz real do filme).

Faz streaming do audio direto pro ffplay -> baixa latencia (comeca a falar
antes de baixar tudo). PT e EN com o mesmo timbre (eleven_multilingual_v2).
"""
import re
import subprocess
import logging

import requests

from .. import config

logger = logging.getLogger(__name__)

_URL = "https://api.elevenlabs.io/v1/text-to-speech/{vid}/stream"
_URL_FULL = "https://api.elevenlabs.io/v1/text-to-speech/{vid}"


def synthesize(text: str) -> bytes:
    """Gera o audio (mp3) e retorna os bytes — usado pela UI web (toca no browser)."""
    if not text.strip():
        return b""
    text = normalize_for_speech(text)
    config.require("ELEVENLABS_API_KEY", config.ELEVENLABS_API_KEY)
    payload = {
        "text": text,
        "model_id": config.ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": 0.5, "similarity_boost": 0.9,
            "style": 0.0, "use_speaker_boost": True,
        },
    }
    headers = {
        "xi-api-key": config.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    r = requests.post(_URL_FULL.format(vid=config.JARVIS_VOICE_ID),
                      json=payload, headers=headers, timeout=60)
    if r.status_code != 200:
        logger.error("ElevenLabs %s: %s", r.status_code, r.text[:200])
        return b""
    return r.content

# "J.A.R.V.I.S." (pontuado) faz o TTS soletrar. Normaliza para a palavra "Jarvis".
_JARVIS_DOTTED = re.compile(r"\bJ\.?\s*A\.?\s*R\.?\s*V\.?\s*I\.?\s*S\.?", re.IGNORECASE)


def normalize_for_speech(text: str) -> str:
    """Ajustes para a fala soar natural (evita soletrar siglas)."""
    return _JARVIS_DOTTED.sub("Jarvis", text)


def speak(text: str) -> None:
    """Fala o texto na voz do Jarvis (bloqueante ate terminar)."""
    if not text.strip():
        return
    text = normalize_for_speech(text)
    config.require("ELEVENLABS_API_KEY", config.ELEVENLABS_API_KEY)

    payload = {
        "text": text,
        "model_id": config.ELEVENLABS_MODEL,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.9,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }
    headers = {
        "xi-api-key": config.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }

    try:
        ffplay = subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-"],
            stdin=subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.error("ffplay nao encontrado (instale ffmpeg).")
        return

    try:
        with requests.post(
            _URL.format(vid=config.JARVIS_VOICE_ID),
            json=payload, headers=headers, stream=True, timeout=60,
        ) as r:
            if r.status_code != 200:
                logger.error("ElevenLabs %s: %s", r.status_code, r.text[:200])
                return
            for chunk in r.iter_content(chunk_size=4096):
                if chunk:
                    ffplay.stdin.write(chunk)
    finally:
        try:
            ffplay.stdin.close()
        except Exception:
            pass
        ffplay.wait()
