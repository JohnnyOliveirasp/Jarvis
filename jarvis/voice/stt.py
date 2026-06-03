"""Transcricao do comando falado via Groq Whisper (rapido e barato)."""
import io
import wave
import logging

from groq import Groq

from .. import config

logger = logging.getLogger(__name__)
_client = Groq(api_key=config.require("GROQ_API_KEY", config.GROQ_API_KEY))


def _pcm_to_wav(pcm: bytes) -> io.BytesIO:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(config.SAMPLE_RATE)
        w.writeframes(pcm)
    buf.name = "command.wav"
    buf.seek(0)
    return buf


def transcribe(pcm: bytes, prompt: str = "") -> str:
    """PCM16 mono -> texto. Retorna '' se vazio/silencio.

    `prompt` biases vocabulary, but DO NOT pass a phrase containing the wake word:
    on silence/echo Whisper echoes the prompt back, which then fires false wake
    triggers. Default is empty for that reason.
    """
    if len(pcm) < config.SAMPLE_RATE:  # < ~0.5s
        return ""
    wav = _pcm_to_wav(pcm)
    kwargs = dict(file=wav, model=config.WHISPER_MODEL, response_format="text")
    if prompt:
        kwargs["prompt"] = prompt
    try:
        text = _client.audio.transcriptions.create(**kwargs)
        result = (text or "").strip()
        logger.info("Transcrito: %s", result)
        return result
    except Exception as e:
        logger.error("Falha na transcricao: %s", e)
        return ""
