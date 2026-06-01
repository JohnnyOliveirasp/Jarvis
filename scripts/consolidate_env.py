"""Consolida o .env do Jarvis: copia ANTHROPIC/OPENAI/GROQ do EntrevistaAI e
garante JARVIS_VOICE_ID. NUNCA imprime valores de segredo — so os nomes."""
from pathlib import Path

JARVIS_ENV = Path(__file__).resolve().parent.parent / ".env"
SRC_ENV = Path(r"C:\Users\johnn\Downloads\Desenvolvimento\Codigos\Python\EntrevistaAI\.env")

WANT = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY"]


def parse(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def main():
    cur = parse(JARVIS_ENV)
    src = parse(SRC_ENV)

    filled = []
    for k in WANT:
        if not cur.get(k) and src.get(k):
            cur[k] = src[k]
            filled.append(k)

    # Trava a voz clonada do filme
    cur.setdefault("JARVIS_VOICE_ID", "BIwnXtEmkY93gFkOYrCg")

    # Reescreve o .env preservando comentario de topo
    lines = [
        "# ─────────────────────────────────────────────",
        "#  Jarvis — environment variables (NEVER commit)",
        "# ─────────────────────────────────────────────",
        f"ELEVENLABS_API_KEY={cur.get('ELEVENLABS_API_KEY','')}",
        f"JARVIS_VOICE_ID={cur.get('JARVIS_VOICE_ID','')}",
        "",
        f"ANTHROPIC_API_KEY={cur.get('ANTHROPIC_API_KEY','')}",
        f"OPENAI_API_KEY={cur.get('OPENAI_API_KEY','')}",
        f"GROQ_API_KEY={cur.get('GROQ_API_KEY','')}",
        "",
    ]
    JARVIS_ENV.write_text("\n".join(lines), encoding="utf-8")

    print("Chaves copiadas do EntrevistaAI:", filled or "(nenhuma necessaria)")
    print("Presentes no .env (nome / tem-valor):")
    for k in ["ELEVENLABS_API_KEY", "JARVIS_VOICE_ID", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY"]:
        print(f"  {k}: {'OK' if cur.get(k) else 'VAZIO'}")


if __name__ == "__main__":
    main()
