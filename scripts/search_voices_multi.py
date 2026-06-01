"""Busca na Voice Library da ElevenLabs por varios termos ligados ao Jarvis real
(Paul Bettany / Iron Man) para achar um clone fiel ao filme. Baixa previas."""
import os, json, urllib.request, urllib.error
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "artifacts" / "jarvis_voices" / "candidatos"
OUT.mkdir(parents=True, exist_ok=True)

for line in (BASE / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("="); os.environ.setdefault(k.strip(), v.strip())
KEY = os.environ["ELEVENLABS_API_KEY"].strip()
API, H = "https://api.elevenlabs.io", {"xi-api-key": os.environ["ELEVENLABS_API_KEY"].strip()}

def get(p):
    with urllib.request.urlopen(urllib.request.Request(API+p, headers=H), timeout=30) as r:
        return json.loads(r.read().decode())

def dl(url, dest):
    try:
        with urllib.request.urlopen(url, timeout=30) as r: dest.write_bytes(r.read())
        return True
    except Exception: return False

terms = ["bettany", "paul bettany", "iron man", "tony stark assistant", "vision marvel", "ai butler", "movie jarvis"]
seen = set()
n = 0
for t in terms:
    try:
        voices = get(f"/v1/shared-voices?page_size=20&search={urllib.parse.quote(t)}").get("voices", [])
    except Exception as e:
        print(f"[{t}] erro: {e}"); continue
    print(f"\n=== termo: '{t}' -> {len(voices)} ===")
    for v in voices:
        vid = v.get("voice_id")
        if vid in seen: continue
        seen.add(vid)
        name = v.get("name","?"); desc = (v.get("description") or "")[:90]
        acc = v.get("accent","?"); gen = v.get("gender","?"); clones = v.get("cloned_by_count",0)
        print(f"  - {name} | {gen}/{acc} | usos:{clones} | id={vid}")
        print(f"    {desc}")
        if v.get("preview_url"):
            n += 1
            safe = "".join(c for c in name if c.isalnum() or c in " -_")[:25].strip().replace(" ","_")
            if dl(v["preview_url"], OUT / f"{n:02d}_{safe}.mp3"):
                print(f"    previa: {n:02d}_{safe}.mp3")

print(f"\n{len(seen)} vozes unicas, {n} previas em {OUT}")
