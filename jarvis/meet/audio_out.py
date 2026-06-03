"""Faz o Jarvis FALAR dentro da reuniao, pelo microfone virtual (VB-CABLE).

Cadeia: voz do ElevenLabs (mp3) -> ffmpeg decodifica p/ PCM float32 mono ->
sounddevice toca no dispositivo de SAIDA "CABLE Input". Como o Chrome do bot
usa "CABLE Output" como microfone, a reuniao ouve o Jarvis.

Nao precisa de lib nova: usa ffmpeg (ja instalado p/ a UI) + sounddevice (ja no venv).
"""
import logging
import subprocess

import numpy as np
import sounddevice as sd

from .. import config

logger = logging.getLogger(__name__)

_PLAY_RATE = 48000  # VB-CABLE roda bem a 48k


def find_output_device(name_substr: str):
    """Indice do 1o dispositivo de SAIDA cujo nome contem name_substr."""
    name_substr = name_substr.lower()
    for i, d in enumerate(sd.query_devices()):
        if name_substr in d["name"].lower() and d["max_output_channels"] > 0:
            return i
    return None


def _mp3_to_pcm(mp3: bytes, rate: int = _PLAY_RATE) -> np.ndarray:
    """Decodifica mp3 -> float32 mono no sample rate pedido (via ffmpeg em pipe)."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "quiet",
             "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", str(rate), "pipe:1"],
            input=mp3, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        return np.frombuffer(proc.stdout, dtype=np.float32)
    except FileNotFoundError:
        logger.error("ffmpeg nao encontrado — nao consigo tocar voz no VB-CABLE.")
        return np.array([], dtype=np.float32)


def speak_pcm_to_cable(mp3: bytes, device_substr: str | None = None) -> float:
    """Toca a voz (mp3) no VB-CABLE e BLOQUEIA ate terminar. Retorna duracao (s)."""
    if not mp3:
        return 0.0
    device_substr = device_substr or config.MEET_SPEAK_DEVICE
    data = _mp3_to_pcm(mp3, _PLAY_RATE)
    if data.size == 0:
        return 0.0
    dev = find_output_device(device_substr)
    if dev is None:
        logger.error("Dispositivo de saida %r nao encontrado (VB-CABLE instalado?).",
                     device_substr)
        return 0.0
    logger.info("Falando na reuniao via %r (%.1fs)", device_substr, data.size / _PLAY_RATE)
    try:
        sd.play(data, _PLAY_RATE, device=dev)
        sd.wait()
    except Exception as e:
        logger.error("Falha ao tocar no VB-CABLE: %s", e)
    return data.size / _PLAY_RATE
