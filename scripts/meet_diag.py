"""Diagnostico: por que o Meet fica carregando no Chrome automatizado?

Abre o perfil do bot, vai pro meet.google.com com os MESMOS args do bot, captura
erros de console/pageerror/requests que falharam, tira screenshots e fecha sozinho.
NAO e interativo (fecha apos ~35s).

Rodar (feche antes qualquer janela do bot/login p/ nao travar o perfil):
  python -m scripts.meet_diag
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import config  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

SHOTS = Path(__file__).resolve().parent.parent / "_ImagesPrj"
SHOTS.mkdir(exist_ok=True)

ARGS = [
    "--use-fake-ui-for-media-stream",
    "--disable-blink-features=AutomationControlled",
    "--start-maximized",
]


def main():
    console, errors, failed = [], [], []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=config.MEET_USER_DATA_DIR,
            channel=config.MEET_BROWSER_CHANNEL,
            headless=False,
            args=ARGS,
            ignore_default_args=["--mute-audio", "--enable-automation"],
            no_viewport=True,
            permissions=["microphone", "camera"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("console", lambda m: console.append(f"[{m.type}] {m.text}"[:300]))
        page.on("pageerror", lambda e: errors.append(str(e)[:300]))
        page.on("requestfailed",
                lambda r: failed.append(f"{r.failure} {r.url}"[:200]))

        print(">> webdriver flag:", end=" ")
        try:
            page.goto("https://meet.google.com/", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print("\n   goto erro:", repr(e)[:200])
        try:
            print(page.evaluate("() => navigator.webdriver"))
        except Exception:
            print("?")

        time.sleep(8)
        page.screenshot(path=str(SHOTS / "diag_1_home.png"))
        print(">> URL:", page.url)
        print(">> TITULO:", page.title())

        # tenta achar o botao "Nova reuniao" e clicar
        for sel in ['button:has-text("Nova reunião")', 'button:has-text("New meeting")',
                    'button:has-text("Reunião")']:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    print(">> achei botao:", sel)
                    loc.click(timeout=4000)
                    break
            except Exception:
                pass
        time.sleep(3)
        # clica "iniciar reuniao instantanea" se aparecer
        for sel in ['*:has-text("Iniciar uma reunião instantânea")',
                    '*:has-text("Start an instant meeting")']:
            try:
                loc = page.locator(sel).last
                if loc.count() > 0:
                    loc.click(timeout=4000)
                    print(">> cliquei iniciar instantanea")
                    break
            except Exception:
                pass
        time.sleep(9)
        page.screenshot(path=str(SHOTS / "diag_2_meeting.png"))
        print(">> URL final:", page.url)

        print("\n=== PAGEERRORS ===")
        for e in errors[-12:]:
            print("  ", e)
        print("=== REQUESTS FALHADOS ===")
        for f in failed[-15:]:
            print("  ", f)
        print("=== CONSOLE (ultimas) ===")
        for c in console[-15:]:
            print("  ", c)
        ctx.close()
    print("\nScreenshots em _ImagesPrj/diag_1_home.png e diag_2_meeting.png")


if __name__ == "__main__":
    main()
