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

# ── Reuniao (Google Meet via Playwright) ──
# Perfil Chrome persistente: voce loga no Google UMA vez (scripts/meet_login.py)
# e a sessao fica salva aqui. NUNCA comitar essa pasta (esta no .gitignore).
MEET_USER_DATA_DIR = os.getenv(
    "MEET_USER_DATA_DIR", str(BASE_DIR / ".chrome_meet_profile")
)
MEET_HEADLESS = os.getenv("MEET_HEADLESS", "0") == "1"   # headed por padrao (anti-bot)
# Usar o Chrome REAL (canal), nao o Chromium da Playwright: o Meet precisa dos
# codecs proprietarios (H.264) que SO existem no Chrome — no Chromium ele trava.
MEET_BROWSER_CHANNEL = os.getenv("MEET_BROWSER_CHANNEL", "chrome")
# Default account planned for the Meet bot profile.
MEET_BOT_EMAIL = os.getenv("MEET_BOT_EMAIL", "support@cvpunch.ai")
# Used by the UI join button. Voice commands can generate this intro in any
# meeting language and pass it through the meeting-start tool.
MEET_DEFAULT_INTRO = os.getenv(
    "MEET_DEFAULT_INTRO",
    "Hello everyone, I am Jarvis, Johnny's assistant. I will take notes for this meeting. Thank you.",
)
# Microfone virtual por onde o Jarvis FALA na reuniao (VB-CABLE).
# O Chrome usa "CABLE Output" como mic; nos tocamos a voz no "CABLE Input".
MEET_SPEAK_DEVICE = os.getenv("MEET_SPEAK_DEVICE", "CABLE Input")
# Microfone que o Chrome do bot DEVE usar dentro do Meet, p/ a sala ouvir a voz.
# CUIDADO: pode haver dois "CABLE Output" (VB-Audio Virtual Cable x VB-Audio
# Point). O certo e o "Virtual Cable" — o mesmo cabo onde tocamos (CABLE Input).
# O bot forca esse device interceptando o getUserMedia do Meet (ver meet/bot.py),
# entao nao depende de selecionar na mao nas Configuracoes do Meet.
MEET_MIC_DEVICE = os.getenv("MEET_MIC_DEVICE", "CABLE Output (VB-Audio Virtual Cable)")
# Nome (no Meet) usado pra "chamar" o Jarvis quando ele estiver mutado ouvindo.
MEET_WAKE_NAME = os.getenv("MEET_WAKE_NAME", "jarvis")
# Como o Jarvis OUVE a sala:
#   "1" (padrao) -> le as LEGENDAS (CC) do proprio Google Meet (texto ja transcrito
#                   pelo Google, qualidade alta — resolve "drivers" no lugar de "Jarvis").
#   "0"          -> grampeia o audio e transcreve no Whisper (caminho antigo, fragil).
MEET_USE_CAPTIONS = os.getenv("MEET_USE_CAPTIONS", "1") == "1"
# Nome do bot como aparece na reuniao (conta Google do bot). Usado pra IGNORAR
# as legendas da propria voz do Jarvis (senao ele se auto-dispararia). Ajuste se
# o nome exibido for outro.
MEET_BOT_DISPLAY_NAME = os.getenv("MEET_BOT_DISPLAY_NAME", "")
# Seu nome como aparece na legenda do Meet (o "dono"). Comandos de ata ditos por
# voce funcionam SEM precisar dizer "Jarvis"; de outras pessoas, exige o nome.
# Casa por substring (ex.: "Johnny" casa "Johnny Marcos"). Ajuste se necessario.
MEET_OWNER_NAME = os.getenv("MEET_OWNER_NAME", "Johnny")
# Nome que o bot digita quando o Meet pede "Seu nome" (modo convidado), antes de
# clicar em "Ask to join". Entrar como convidado evita o conflito de ser a MESMA
# conta Google que voce (que faz o Meet desconectar/"sair da reuniao").
MEET_JOIN_NAME = os.getenv("MEET_JOIN_NAME", "Jarvis")
# Modo "solto" do dono: qualquer PERGUNTA/PEDIDO seu (dono) e respondido mesmo sem
# dizer "Jarvis". Util quando voce esta conduzindo; pode incomodar em reuniao cheia
# (ele responde tambem o que voce fala pros colegas). "0" = exige "Jarvis"/comando.
MEET_OWNER_OPEN = os.getenv("MEET_OWNER_OPEN", "1") == "1"

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
