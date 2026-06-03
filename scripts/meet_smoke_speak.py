"""Isolated Google Meet speak smoke test.

Goal:
  open Chrome profile -> join Meet -> confirm in call -> speak one phrase.

This uses the production MeetBot path plus ElevenLabs TTS and VB-CABLE output.
Close any previous MeetBot/smoke-test Chrome before running, because the
persistent Chrome profile can only be opened by one Playwright process.

Run:
  python -m scripts.meet_smoke_speak "https://meet.google.com/abc-defg-hij"
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.meet.bot import MeetBot  # noqa: E402
from jarvis.voice import tts  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

SHOTS = Path(__file__).resolve().parent.parent / "_ImagesPrj"
SHOTS.mkdir(exist_ok=True)
STATE_FILE = SHOTS / "speak_state.json"

DEFAULT_TEXT = (
    "Hello everyone, I am Jarvis, Johnny's assistant. "
    "I will take notes for this meeting. Thank you."
)


def write_state(payload):
    payload = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        **payload,
    }
    STATE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f">> state: _ImagesPrj/speak_state.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--leave", action="store_true", help="Leave the call after speaking.")
    args = parser.parse_args()

    url = (args.url or "").strip()
    if not url:
        url = input("Meet URL: ").strip()
    if not url:
        print("No Meet URL provided.")
        return 2

    text = (args.text or DEFAULT_TEXT).strip()
    bot = MeetBot(on_event=lambda k, m: print(f"  [{k}] {m}"))
    bot.start()

    print(">> Joining and confirming in_call...")
    ok, val = bot.join(url)
    print(f">> JOIN ok={ok}: {val} | in_call={bot.in_call}")
    if not ok or not bot.in_call:
        write_state({
            "status": "join_failed",
            "join_ok": ok,
            "join_value": val,
            "in_call": bool(bot.in_call),
            "url": url,
        })
        return 1

    bot.screenshot(str(SHOTS / "speak_before.png"))
    print(">> screenshot: _ImagesPrj/speak_before.png")

    print(f">> Generating voice: {text}")
    mp3 = tts.synthesize(text)
    if not mp3:
        write_state({
            "status": "tts_failed",
            "join_ok": ok,
            "join_value": val,
            "in_call": bool(bot.in_call),
            "text": text,
            "url": url,
        })
        print(">> TTS failed or returned empty audio.")
        return 1

    print(f">> Speaking ({len(mp3)} bytes)...")
    speak_ok, speak_val = bot.speak(mp3)
    print(f">> SPEAK ok={speak_ok}: {speak_val}")

    bot.screenshot(str(SHOTS / "speak_after.png"))
    print(">> screenshot: _ImagesPrj/speak_after.png")

    if args.leave:
        bot.leave()

    spoke = bool(speak_ok and speak_val == "spoke in the meeting")
    write_state({
        "status": "success" if spoke else "speak_failed",
        "join_ok": ok,
        "join_value": val,
        "in_call": bool(bot.in_call),
        "speak_ok": speak_ok,
        "speak_value": speak_val,
        "text": text,
        "audio_bytes": len(mp3),
        "url": url,
    })

    print(">> Done. Chrome stays open. Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
