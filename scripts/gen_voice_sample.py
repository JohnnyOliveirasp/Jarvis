"""
Gera amostras da voz do Jarvis via ElevenLabs (sem dependencias externas: usa urllib).
- Lista as vozes da conta, escolhe uma britanica masculina (estilo mordomo).
- Gera uma amostra em ingles e outra em portugues.
- Salva os .mp3 em Jarvis/artifacts/.
"""
import os
import json
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS = BASE_DIR / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# Carrega ELEVENLABS_API_KEY do .env (parser minimo, sem python-dotenv)
def load_env():
    env_path = BASE_DIR / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

load_env()
API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
if not API_KEY:
    raise SystemExit("ELEVENLABS_API_KEY nao encontrada no .env")

API = "https://api.elevenlabs.io"
HEADERS = {"xi-api-key": API_KEY}

# Vozes premade conhecidas (fallback caso a conta nao exponha labels)
FALLBACK_BRITISH_MALE = [
    ("Daniel", "onwK4e9ZLuTAKqWW03F9"),   # britanico, grave, autoritario (estilo Jarvis)
    ("George", "JBFqnCBsd6RMkjVDRZzb"),   # britanico, quente
]


def http_get(path):
    req = urllib.request.Request(API + path, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def pick_voice():
    """Tenta achar uma voz britanica masculina na conta; senao usa fallback."""
    try:
        data = http_get("/v1/voices")
        voices = data.get("voices", [])
        print(f"[info] {len(voices)} vozes disponiveis na conta")
        # 1) procura britanica + masculina pelos labels
        for v in voices:
            labels = {k: (str(val).lower() if val else "") for k, val in (v.get("labels") or {}).items()}
            acc = labels.get("accent", "")
            gen = labels.get("gender", "")
            if "british" in acc and "male" in gen and "female" not in gen:
                print(f"[pick] britanica masculina: {v['name']} ({v['voice_id']})")
                return v["name"], v["voice_id"]
        # 2) qualquer voz masculina
        for v in voices:
            labels = {k: (str(val).lower() if val else "") for k, val in (v.get("labels") or {}).items()}
            if "male" in labels.get("gender", "") and "female" not in labels.get("gender", ""):
                print(f"[pick] masculina (sem accent britanico): {v['name']} ({v['voice_id']})")
                return v["name"], v["voice_id"]
        # 3) primeira disponivel
        if voices:
            v = voices[0]
            print(f"[pick] primeira disponivel: {v['name']} ({v['voice_id']})")
            return v["name"], v["voice_id"]
    except urllib.error.HTTPError as e:
        print(f"[warn] /v1/voices falhou ({e.code}); usando fallback")
    except Exception as e:
        print(f"[warn] erro listando vozes: {e}; usando fallback")
    name, vid = FALLBACK_BRITISH_MALE[0]
    print(f"[pick] fallback: {name} ({vid})")
    return name, vid


def tts(voice_id, text, out_path, model="eleven_multilingual_v2"):
    body = json.dumps({
        "text": text,
        "model_id": model,
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.85,
            "style": 0.35,
            "use_speaker_boost": True,
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{API}/v1/text-to-speech/{voice_id}",
        data=body,
        headers={**HEADERS, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            audio = r.read()
        out_path.write_bytes(audio)
        print(f"[ok] {out_path.name} ({len(audio)//1024} KB)")
        return True
    except urllib.error.HTTPError as e:
        print(f"[ERRO] TTS falhou ({e.code}): {e.read().decode('utf-8', 'ignore')[:300]}")
        return False


if __name__ == "__main__":
    name, vid = pick_voice()

    samples = {
        "jarvis_en.mp3": (
            "Good evening, sir. J.A.R.V.I.S. online and at your service. "
            "All systems are operational. Shall I join your meeting?"
        ),
        "jarvis_pt.mp3": (
            "Boa noite, senhor. J.A.R.V.I.S. online e ao seu dispor. "
            "Todos os sistemas operacionais. Deseja que eu entre na reuniao?"
        ),
    }

    ok = True
    for fname, text in samples.items():
        ok = tts(vid, text, ARTIFACTS / fname) and ok

    print("\n=== RESUMO ===")
    print(f"Voz usada: {name} ({vid})")
    print(f"Arquivos em: {ARTIFACTS}")
    print("OK" if ok else "Houve erro em alguma amostra")
