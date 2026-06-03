"""Sondagem do join: navega ate uma reuniao, tenta entrar e tira prints em cada
etapa, capturando se a aba fecha e por que. NAO e interativo.

Uso:
  python -m scripts.meet_probe "https://meet.google.com/xxx-xxxx-xxx"
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import config  # noqa: E402
from jarvis.meet import selectors as S  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

SHOTS = Path(__file__).resolve().parent.parent / "_ImagesPrj"
SHOTS.mkdir(exist_ok=True)

ARGS = [
    "--use-fake-ui-for-media-stream",
    "--disable-blink-features=AutomationControlled",
    "--start-maximized",
    "--disable-popup-blocking",
]


def shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / name))
        print(f">> shot {name} OK")
    except Exception as e:
        print(f">> shot {name} FAIL: {repr(e)[:160]}")


def buttons(page):
    try:
        return page.evaluate(
            """() => [...document.querySelectorAll('button,[role=button]')]
                 .map(b => (b.getAttribute('aria-label')||b.innerText||'').trim())
                 .filter(Boolean).slice(0,40)""")
    except Exception as e:
        return f"(buttons err: {repr(e)[:120]})"


def signed_in(page):
    try:
        return page.evaluate(
            """() => {
              const t = document.body ? document.body.innerText : '';
              const m = t.match(/[a-z0-9._%+-]+@[a-z0-9.-]+/i);
              return m ? m[0] : null;
            }""")
    except Exception:
        return None


def click_first(page, sels, timeout=2500):
    for sel in sels:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            loc.wait_for(state="visible", timeout=timeout)
            loc.click()
            return sel
        except Exception:
            continue
    return None


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else config.MEET_USER_DATA_DIR
    closed = {"flag": False}
    console, errors = [], []
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
        page.on("close", lambda *_: (closed.__setitem__("flag", True), print(">> !!! PAGE CLOSE EVENT")))
        page.on("console", lambda m: console.append(f"[{m.type}] {m.text}"[:200]))
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))

        print(">> navigating to", url)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(">> goto error:", repr(e)[:200])
        time.sleep(4)
        print(">> url:", page.url, "| signed_in_hint:", signed_in(page))
        print(">> buttons(lobby):", buttons(page))
        shot(page, "probe_1_lobby.png")

        # name field?
        nbox = None
        for sel in S.NAME_INPUT:
            loc = page.locator(sel).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    nbox = loc
                    print(">> NAME field present via", sel)
                    break
            except Exception:
                pass
        if nbox is not None:
            try:
                nbox.click(); nbox.fill(config.MEET_JOIN_NAME)
                print(">> filled name:", config.MEET_JOIN_NAME)
            except Exception as e:
                print(">> fill name err:", repr(e)[:160])
        else:
            print(">> NO name field (likely signed-in mode)")
        shot(page, "probe_2_named.png")

        if "check" in sys.argv:
            print(">> CHECK mode: NOT clicking join. Signed-in?",
                  "NO (Sign in present)" if "Sign in" in str(buttons(page)) else "looks signed-in / no Sign in button")
            try:
                ctx.close()
            except Exception:
                pass
            print(">> done (check). prints em _ImagesPrj/probe_*.png")
            return

        used = click_first(page, S.JOIN_NOW) or click_first(page, S.ASK_TO_JOIN)
        print(">> join click selector:", used)
        for i in range(1, 7):
            time.sleep(2)
            if closed["flag"]:
                print(f">> page CLOSED around {i*2}s after click")
                break
            try:
                print(f">> t={i*2}s url={page.url}")
            except Exception as e:
                print(f">> t={i*2}s page dead: {repr(e)[:120]}")
                break
        if not closed["flag"]:
            shot(page, "probe_3_after.png")
            print(">> buttons(after):", buttons(page))

        print("=== pageerrors ===")
        for e in errors[-10:]:
            print("  ", e)
        print("=== console (last) ===")
        for c in console[-12:]:
            print("  ", c)
        try:
            ctx.close()
        except Exception:
            pass
    print(">> done. prints em _ImagesPrj/probe_*.png")


if __name__ == "__main__":
    main()
