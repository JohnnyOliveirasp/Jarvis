"""
Procura a voz 'Jarvis' na Voice Library da ElevenLabs, baixa as previas dos
candidatos para comparacao e gera uma amostra EN+PT com o melhor match.
Sem dependencias externas (urllib).
"""
import os
import json
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUT = BASE_DIR / "artifacts" / "jarvis_voices"
OUT.mkdir(parents=True, exist_ok=True)

def load_env():
    for line in (BASE_DIR / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

load_env()
API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
if not API_KEY:
    raise SystemExit("ELEVENLABS_API_KEY nao encontrada no .env")

API = "https://api.elevenlabs.io"
H = {"xi-api-key": API_KEY}

# ID de uma voz 'Jarvis' publica encontrada na pesquisa (fallback p/ gerar direto)
KNOWN_JARVIS_VOICE_ID = "WWtyH2oxeOp9yZwK8ERD"


def get(path):
    req = urllib.request.Request(API + path, headers=H)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def download(url, dest):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            dest.write_bytes(r.read())
        return True
    except Exception as e:
        print(f"   [warn] preview falhou: {e}")
        return False


def search_shared(query):
    try:
        data = get(f"/v1/shared-voices?page_size=30&search={query}")
        return data.get("voices", [])
    except urllib.error.HTTPError as e:
        print(f"[warn] shared-voices {e.code}: {e.read().decode('utf-8','ignore')[:200]}")
    except Exception as e:
        print(f"[warn] shared-voices erro: {e}")
    return []


def add_shared(public_owner_id, voice_id, new_name):
    body = json.dumps({"new_name": new_name}).encode("utf-8")
    req = urllib.request.Request(
        f"{API}/v1/voices/add/{public_owner_id}/{voice_id}",
        data=body, headers={**H, "Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8")).get("voice_id")


def tts(voice_id, text, dest, model="eleven_multilingual_v2"):
    body = json.dumps({
        "text": text, "model_id": model,
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.9, "style": 0.3, "use_speaker_boost": True},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{API}/v1/text-to-speech/{voice_id}", data=body,
        headers={**H, "Content-Type": "application/json", "Accept": "audio/mpeg"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            dest.write_bytes(r.read())
        print(f"   [ok] {dest.name}")
        return True
    except urllib.error.HTTPError as e:
        print(f"   [ERRO] tts {e.code}: {e.read().decode('utf-8','ignore')[:200]}")
        return False


if __name__ == "__main__":
    print("=== Buscando 'jarvis' na Voice Library ===")
    voices = search_shared("jarvis")
    print(f"{len(voices)} candidatos encontrados\n")

    candidates = []
    for i, v in enumerate(voices[:12], 1):
        name = v.get("name", "?")
        vid = v.get("voice_id")
        owner = v.get("public_owner_id")
        accent = v.get("accent", "?")
        gender = v.get("gender", "?")
        desc = (v.get("description") or "")[:80]
        clones = v.get("cloned_by_count", 0)
        preview = v.get("preview_url")
        print(f"[{i}] {name} | {gender}/{accent} | usos:{clones}")
        print(f"     id={vid} owner={owner}")
        print(f"     {desc}")
        if preview:
            safe = "".join(c for c in name if c.isalnum() or c in " -_")[:30].strip().replace(" ", "_")
            if download(preview, OUT / f"{i:02d}_{safe}.mp3"):
                print(f"     previa salva: {i:02d}_{safe}.mp3")
        candidates.append({"name": name, "voice_id": vid, "owner": owner, "name_l": name.lower()})
        print()

    # Escolhe o melhor: nome contem 'jarvis'
    best = next((c for c in candidates if "jarvis" in c["name_l"]), candidates[0] if candidates else None)

    print("=== Gerando amostra com o melhor candidato ===")
    gen_voice_id = None
    if best:
        print(f"Melhor: {best['name']} ({best['voice_id']})")
        try:
            gen_voice_id = add_shared(best["owner"], best["voice_id"], "Jarvis")
            print(f"Adicionado a conta como 'Jarvis' -> {gen_voice_id}")
        except urllib.error.HTTPError as e:
            print(f"[warn] add falhou {e.code}: {e.read().decode('utf-8','ignore')[:200]}")
            gen_voice_id = best["voice_id"]  # tenta direto
        except Exception as e:
            print(f"[warn] add erro: {e}")
            gen_voice_id = best["voice_id"]

    if not gen_voice_id:
        print(f"Sem candidato; tentando ID conhecido {KNOWN_JARVIS_VOICE_ID}")
        gen_voice_id = KNOWN_JARVIS_VOICE_ID

    en = "Good evening, sir. J.A.R.V.I.S. online and at your service. All systems are operational."
    pt = "Boa noite, senhor. J.A.R.V.I.S. online e ao seu dispor. Todos os sistemas operacionais."
    ok1 = tts(gen_voice_id, en, OUT / "JARVIS_sample_en.mp3")
    ok2 = tts(gen_voice_id, pt, OUT / "JARVIS_sample_pt.mp3")

    print("\n=== RESUMO ===")
    print(f"voice_id usado: {gen_voice_id}")
    print(f"Previas + amostras em: {OUT}")
