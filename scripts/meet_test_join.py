"""Teste REAL da Fase 1: o bot entra numa reuniao usando o codigo de producao.

Uso:
  python -m scripts.meet_test_join "https://meet.google.com/xxx-xxxx-xxx"

Abre o Chrome do bot (perfil logado), entra na reuniao (camera+mic off), tira um
screenshot e deixa a janela aberta. Voce ADMITE o bot na sua reuniao. Ctrl+C sai.
"""
import logging
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# mostra TODOS os logs do bot (passo-a-passo do join, diagnostico, etc.)
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                    datefmt="%H:%M:%S")

from jarvis.meet.bot import MeetBot  # noqa: E402

SHOTS = Path(__file__).resolve().parent.parent / "_ImagesPrj"


def main():
    if len(sys.argv) < 2:
        print("Faltou o link. Ex: python -m scripts.meet_test_join \"https://meet.google.com/abc-defg-hij\"")
        return
    url = sys.argv[1]
    bot = MeetBot(on_event=lambda k, m: print(f"  [{k}] {m}"))
    bot.start()
    print(">> Entrando... (ADMITA o bot na sua reuniao quando ele pedir)")
    ok, val = bot.join(url)
    print(f">> JOIN ok={ok}: {val}")
    SHOTS.mkdir(exist_ok=True)
    state = {
        "ok": ok,
        "value": val,
        "in_call": bool(bot.in_call),
        "url": url,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (SHOTS / "join_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f">> state: _ImagesPrj/join_state.json in_call={state['in_call']}")
    try:
        bot.screenshot(str(SHOTS / "join_result.png"))
        print(">> screenshot: _ImagesPrj/join_result.png")
    except Exception as e:
        print(">> screenshot falhou:", e)
    print(">> Janela aberta. Ctrl+C para sair.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bot.leave()


if __name__ == "__main__":
    main()
