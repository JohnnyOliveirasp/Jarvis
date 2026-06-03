"""Isolated Google Meet join smoke test.

Goal: prove only this path:
  open Chrome profile -> open Meet URL -> click join/request -> confirm in call.

It does not use MeetBot, TTS, notes, listener, websocket, or VB-CABLE.

Run:
  python -m scripts.meet_smoke_join "https://meet.google.com/abc-defg-hij"

If no URL is passed, the script asks for it interactively.
"""
import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import config  # noqa: E402
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

SHOTS = Path(__file__).resolve().parent.parent / "_ImagesPrj"
SHOTS.mkdir(exist_ok=True)
STATE_FILE = SHOTS / "smoke_join_state.json"

LAUNCH_ARGS = [
    "--use-fake-ui-for-media-stream",
    "--disable-blink-features=AutomationControlled",
    "--start-maximized",
    "--disable-popup-blocking",
]

DISMISS_SELECTORS = [
    'button:has-text("Got it")',
    'button:has-text("Entendi")',
    'button:has-text("OK")',
    'button[aria-label="Close" i]',
    'button[aria-label="Fechar" i]',
]

MIC_OFF_SELECTORS = [
    'button[aria-label*="Turn off microphone" i]',
    'button[aria-label*="Desativar microfone" i]',
    'div[role="button"][aria-label*="Turn off microphone" i]',
    'div[role="button"][aria-label*="Desativar microfone" i]',
]

CAM_OFF_SELECTORS = [
    'button[aria-label*="Turn off camera" i]',
    'button[aria-label*="Desativar camera" i]',
    'button[aria-label*="Desativar câmera" i]',
    'div[role="button"][aria-label*="Turn off camera" i]',
    'div[role="button"][aria-label*="Desativar camera" i]',
    'div[role="button"][aria-label*="Desativar câmera" i]',
]

NAME_SELECTORS = [
    'input[aria-label="Your name" i]',
    'input[aria-label="Seu nome" i]',
    'input[aria-label*="name" i]',
    'input[aria-label*="nome" i]',
    'input[type="text"]',
]

JOIN_TEXT_RE = (
    "Participar agora|Pedir para participar|Pedir entrada|"
    "Join now|Ask to join|Request to join"
)


def click_first(page, selectors, label, timeout=1500):
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            loc.wait_for(state="visible", timeout=timeout)
            loc.click(timeout=timeout)
            print(f">> {label}: clicked {selector}")
            return True
        except Exception:
            pass
    print(f">> {label}: not found")
    return False


def fill_guest_name(page):
    bot_name = getattr(config, "MEET_BOT_NAME", "Jarvis")
    for selector in NAME_SELECTORS:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0 and loc.is_visible():
                current = (loc.input_value(timeout=1000) or "").strip()
                if not current:
                    loc.fill(bot_name, timeout=3000)
                    print(f">> guest name: filled {bot_name!r}")
                else:
                    print(f">> guest name: already filled {current!r}")
                return True
        except Exception:
            pass
    print(">> guest name: not shown")
    return False


def click_join(page):
    clicked = page.evaluate(
        """(joinTextRe) => {
          const re = new RegExp(joinTextRe, 'i');
          const nodes = [...document.querySelectorAll('button,[role=button],span')];
          const node = nodes.find((el) => {
            const text = (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
            return text && re.test(text);
          });
          if (!node) return null;
          node.click();
          return (node.innerText || node.textContent || node.getAttribute('aria-label') || '').trim();
        }""",
        JOIN_TEXT_RE,
    )
    if clicked:
        print(f">> join: clicked {clicked!r}")
        return True
    print(">> join: button not found")
    return False


def is_in_call(page):
    try:
        return bool(
            page.evaluate(
                """() => {
                  const nodes = [...document.querySelectorAll('button,[role=button]')];
                  const hasLeave = nodes.some((b) => {
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    const text = (b.innerText || '').toLowerCase();
                    return aria.includes('leave call') || aria.includes('end call')
                      || aria.includes('sair da chamada') || aria.includes('salir de la llamada')
                      || text.includes('leave call') || text.includes('sair da chamada');
                  });
                  if (hasLeave) return true;

                  const body = (document.body?.innerText || '').toLowerCase();
                  const hasCallControls = nodes.some((b) => {
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    return aria.includes('chat') || aria.includes('people')
                      || aria.includes('pessoas') || aria.includes('raise hand')
                      || aria.includes('levantar a mao') || aria.includes('levantar a mão');
                  });
                  const stillLobby = body.includes('ask to join')
                    || body.includes('request to join')
                    || body.includes('pedir para participar')
                    || body.includes('join now')
                    || body.includes('participar agora');
                  return hasCallControls && !stillLobby;
                }"""
            )
        )
    except Exception:
        return False


def dump_state(page):
    try:
        return page.evaluate(
            """() => ({
              url: location.href,
              title: document.title,
              webdriver: navigator.webdriver,
              buttons: [...document.querySelectorAll('button,[role=button]')]
                .map((b) => ({
                  text: (b.innerText || '').trim().replace(/\\s+/g, ' '),
                  aria: b.getAttribute('aria-label') || '',
                  visible: !!(b.offsetWidth || b.offsetHeight || b.getClientRects().length)
                }))
                .filter((b) => b.visible && (b.text || b.aria))
                .slice(0, 80),
              inputs: [...document.querySelectorAll('input,textarea')]
                .map((i) => ({
                  type: i.getAttribute('type') || i.tagName,
                  aria: i.getAttribute('aria-label') || '',
                  placeholder: i.getAttribute('placeholder') || '',
                  value: i.value || ''
                }))
                .slice(0, 20),
              body: (document.body?.innerText || '').replace(/\\s+/g, ' ').slice(0, 1200)
            })"""
        )
    except Exception as exc:
        return {"error": str(exc)}


def write_state(status, page, extra=None):
    payload = {
        "status": status,
        "in_call": status == "success",
        "url": getattr(page, "url", None),
        "title": None,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        payload["title"] = page.title()
    except Exception:
        pass
    if extra:
        payload.update(extra)
    STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f">> state: {STATE_FILE}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?")
    parser.add_argument("--timeout", type=int, default=150)
    parser.add_argument("--close", action="store_true", help="Close Chrome after the test.")
    parser.add_argument(
        "--guest-profile",
        action="store_true",
        help="Use a separate clean Chrome profile and join as a guest named Jarvis.",
    )
    args = parser.parse_args()

    url = (args.url or "").strip()
    if not url:
        url = input("Meet URL: ").strip()
    if not url:
        print("No Meet URL provided.")
        return 2

    user_data_dir = Path(config.MEET_USER_DATA_DIR)
    if args.guest_profile:
        user_data_dir = Path(config.BASE_DIR) / ".chrome_meet_smoke_guest"
        if user_data_dir.exists():
            shutil.rmtree(user_data_dir)

    print(f">> profile: {user_data_dir}")
    print(f">> channel: {config.MEET_BROWSER_CHANNEL}")
    print(f">> url: {url}")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            channel=config.MEET_BROWSER_CHANNEL,
            headless=False,
            args=LAUNCH_ARGS,
            ignore_default_args=["--mute-audio", "--enable-automation"],
            no_viewport=True,
            permissions=["microphone", "camera"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.bring_to_front()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except PlaywrightTimeoutError:
            print(">> goto: timed out after domcontentloaded wait, continuing with current page")
        page.wait_for_timeout(5000)
        print(f">> loaded: {page.url} | {page.title()!r}")
        page.screenshot(path=str(SHOTS / "smoke_join_loaded.png"), full_page=False)

        click_first(page, DISMISS_SELECTORS, "dismiss")
        fill_guest_name(page)
        click_first(page, CAM_OFF_SELECTORS, "camera off")
        click_first(page, MIC_OFF_SELECTORS, "mic off")
        clicked = click_join(page)

        if not clicked:
            print(">> visible state before waiting:")
            print(json.dumps(dump_state(page), ensure_ascii=False, indent=2))

        deadline = time.monotonic() + args.timeout
        poll = 0
        while time.monotonic() < deadline:
            if is_in_call(page):
                page.screenshot(path=str(SHOTS / "smoke_join_success.png"), full_page=False)
                write_state("success", page, {"screenshot": str(SHOTS / "smoke_join_success.png")})
                print(">> SUCCESS: in call confirmed")
                print(">> screenshot: _ImagesPrj/smoke_join_success.png")
                if not args.close:
                    print(">> Chrome stays open. Press Ctrl+C here to close the script.")
                    try:
                        while True:
                            time.sleep(1)
                    except KeyboardInterrupt:
                        pass
                ctx.close()
                return 0

            poll += 1
            if poll % 5 == 0:
                print(f">> waiting admission/call confirmation... {poll}s url={page.url}")
                fill_guest_name(page)
                click_join(page)
            page.wait_for_timeout(1000)

        page.screenshot(path=str(SHOTS / "smoke_join_fail.png"), full_page=False)
        write_state("fail", page, {"screenshot": str(SHOTS / "smoke_join_fail.png"), "dom": dump_state(page)})
        print(">> FAIL: did not confirm in call")
        print(">> screenshot: _ImagesPrj/smoke_join_fail.png")
        print(json.dumps(dump_state(page), ensure_ascii=False, indent=2))
        if not args.close:
            print(">> Chrome stays open for inspection. Press Ctrl+C here to close the script.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        ctx.close()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
