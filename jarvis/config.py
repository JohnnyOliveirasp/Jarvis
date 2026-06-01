"""Configuracao central do Jarvis. Carrega o .env e expoe constantes."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ── Voz (ElevenLabs — clone da voz REAL do filme) ──
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
JARVIS_VOICE_ID = os.getenv("JARVIS_VOICE_ID", "BIwnXtEmkY93gFkOYrCg")  # "JARVIS Film"
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")  # voz fiel do clone do filme

# ── Cerebro (Claude Opus) ──
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-8")
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "1024"))

# ── STT (Groq Whisper) ──
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-large-v3-turbo")

# ── Wake word (openWakeWord) ──
WAKE_WORD = os.getenv("WAKE_WORD", "hey_jarvis")        # modelo pre-treinado
WAKE_THRESHOLD = float(os.getenv("WAKE_THRESHOLD", "0.5"))

# ── Audio ──
SAMPLE_RATE = 16000          # 16 kHz mono (padrao p/ wake word + whisper)
FRAME_SAMPLES = 1280         # 80 ms @ 16 kHz (frame do openWakeWord)
VAD_AGGRESSIVENESS = 1       # 0..3 (1 = captura fala mais facilmente)
SILENCE_MS_TO_STOP = 1100    # silencio que encerra a captura do comando
START_TIMEOUT_MS = 4000      # quanto espera voce comecar a falar apos a wake word
MAX_COMMAND_SECONDS = 15     # trava de seguranca

ARTIFACTS_DIR = BASE_DIR / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)


def require(name: str, value: str):
    """Falha cedo e claro se faltar credencial."""
    if not value:
        raise SystemExit(
            f"[config] {name} ausente no .env — preencha antes de rodar o Jarvis."
        )
    return value
