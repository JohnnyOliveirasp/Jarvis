"""MeetBot controls Google Meet from a dedicated Playwright thread.

The sync Playwright API cannot run inside FastAPI's event loop, so the bot owns
a worker thread and receives serialized commands through a queue.

Login uses a persistent Chrome profile from config.MEET_USER_DATA_DIR. Log in
once with scripts/meet_login.py and future runs reuse the saved session.

Audio:
  - Speaking uses VB-CABLE through audio_out. Chrome should use "CABLE Output"
    as its microphone, while Python plays audio to "CABLE Input".
  - Listening taps the meeting page media elements through listener.JS_TAP.

Important launch flag: --use-fake-ui-for-media-stream auto-accepts media
prompts. Do not use --use-fake-device-for-media-stream because that would
replace the real VB-CABLE microphone stream.
"""
import json
import logging
import queue
import threading
import time
from pathlib import Path

from .. import config
from . import audio_out, selectors as S
from .listener import JS_TAP, JS_CAPTIONS, MeetListener
from .notes import MeetingNotes

logger = logging.getLogger(__name__)

_LAUNCH_ARGS = [
    "--use-fake-ui-for-media-stream",          # auto-aceita prompt de mic/cam
    "--disable-blink-features=AutomationControlled",
    "--start-maximized",
    "--disable-popup-blocking",
]


def _force_mic_js() -> str:
    """Init script that forces Meet's microphone to the VB-CABLE device.

    Instead of fighting Meet's fragile Settings dialog, we wrap
    navigator.mediaDevices.getUserMedia so every audio capture is pinned to the
    "CABLE Output (VB-Audio Virtual Cable)" device — the same cable Python plays
    the voice into. This runs before Meet's own code (add_init_script), so the
    room hears Jarvis without anyone selecting the device by hand.
    """
    match = json.dumps((config.MEET_MIC_DEVICE or "cable output").lower())
    return """
    (() => {
      const MATCH = %s;
      const md = navigator.mediaDevices;
      if (!md || !md.getUserMedia) return;
      const pick = async () => {
        try {
          const devs = await md.enumerateDevices();
          const ins = devs.filter(d => d.kind === 'audioinput');
          let c = ins.find(d => (d.label || '').toLowerCase().includes(MATCH));
          if (!c) c = ins.find(d => {
            const l = (d.label || '').toLowerCase();
            return l.includes('cable output') && l.includes('virtual cable');
          });
          return c || null;
        } catch (e) { return null; }
      };
      const orig = md.getUserMedia.bind(md);
      md.getUserMedia = async (constraints) => {
        try {
          if (constraints && constraints.audio) {
            const c = await pick();
            window.__jarvisMicForced = c ? c.label : 'NOT_FOUND';
            if (c) {
              const a = (constraints.audio && typeof constraints.audio === 'object')
                ? Object.assign({}, constraints.audio) : {};
              a.deviceId = { exact: c.deviceId };
              constraints = Object.assign({}, constraints, { audio: a });
            }
          }
        } catch (e) {}
        return orig(constraints);
      };
    })();
    """ % match


class MeetBot:
    def __init__(self, on_event=None):
        self._on_event = on_event or (lambda kind, msg: None)
        self._cmd_q: "queue.Queue" = queue.Queue()
        self._thread = None
        self._running = False
        self._ctx = None
        self._page = None

        self.in_call = False
        self.mic_muted = True
        self.notes = MeetingNotes()
        # The listener taps the room audio. It serves two purposes:
        #   - on_line: feed the live minutes (only shown/stored while notes active)
        #   - on_command: when a participant says the wake name ("Jarvis ..."),
        #     Jarvis answers the room out loud (handled by a tool-less brain, so
        #     participants can never join/leave/control the meeting).
        self._listener = MeetListener(
            self.notes,
            on_line=self._on_note_line,
            on_command=self._on_meeting_command,
        )
        self._tap_injected = False
        self._captions_injected = False
        self._name_filled = False
        self._room_command_suppressed_until = 0.0

    # Public API called from other threads.
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="MeetBot")
        self._thread.start()

    def _call(self, name, timeout=60, **kw):
        """Queue a command and block until the worker returns its result."""
        if not (self._thread and self._thread.is_alive()):
            self.start()
        box: "queue.Queue" = queue.Queue(maxsize=1)
        self._cmd_q.put((name, kw, box))
        try:
            ok, val = box.get(timeout=timeout)
        except queue.Empty:
            return False, "tempo esgotado"
        return ok, val

    def join(self, url: str):
        return self._call("join", timeout=150, url=url)

    def speak(self, mp3: bytes):
        return self._call("speak", timeout=120, mp3=mp3)

    def set_mic(self, muted: bool):
        return self._call("set_mic", timeout=30, muted=muted)

    def post_chat(self, text: str):
        return self._call("post_chat", timeout=45, text=text)

    def start_notes(self):
        return self._call("start_notes", timeout=30)

    def stop_notes(self):
        return self._call("stop_notes", timeout=30)

    def leave(self):
        return self._call("leave", timeout=30)

    def screenshot(self, path: str):
        return self._call("screenshot", timeout=20, path=path)

    # Internal worker thread.
    def _run(self):
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                self._ctx = p.chromium.launch_persistent_context(
                    user_data_dir=config.MEET_USER_DATA_DIR,
                    channel=config.MEET_BROWSER_CHANNEL,   # Chrome real (codecs do Meet)
                    headless=config.MEET_HEADLESS,
                    args=_LAUNCH_ARGS,
                    ignore_default_args=["--mute-audio", "--enable-automation"],
                    no_viewport=True,
                    permissions=["microphone", "camera"],
                )
                # Force the meeting mic to VB-CABLE BEFORE any page script runs,
                # so Meet captures Jarvis's voice without manual device selection.
                self._ctx.add_init_script(_force_mic_js())
                self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
                # Log if the page/context closes unexpectedly (helps diagnose the
                # "tab closed by itself" / duplicate-account disconnect).
                try:
                    self._page.on("close", lambda *_: logger.warning("PAGE close event fired"))
                    self._ctx.on("close", lambda *_: logger.warning("CONTEXT close event fired"))
                except Exception:
                    pass
                # bindings: audio dos participantes (modo antigo) e legendas (modo novo)
                self._ctx.expose_function("__jarvisAudio", self._listener.feed_b64)
                self._ctx.expose_function("__jarvisCaption", self._listener.feed_caption)
                self._loop()
        except Exception:
            logger.exception("MeetBot caiu")
            self._on_event("error", "The meeting browser crashed.")
        finally:
            self._running = False
            self.in_call = False

    def _loop(self):
        while self._running:
            try:
                name, kw, box = self._cmd_q.get(timeout=0.1)
            except queue.Empty:
                try:                       # pump: deixa eventos/bindings fluirem
                    self._page.wait_for_timeout(80)
                except Exception as e:
                    if self._is_browser_closed_error(e):
                        logger.warning("MeetBot browser was closed.")
                        self._running = False
                        self.in_call = False
                        self._on_event("error", "The meeting browser was closed.")
                    pass
                continue
            try:
                handler = getattr(self, f"_do_{name}")
                logger.info("MeetBot >>> %s %s", name, "(audio)" if name == "speak" else kw)
                val = handler(**kw)
                logger.info("MeetBot <<< %s OK: %r", name, val)
                box.put((True, val))
            except Exception as e:
                if self._is_browser_closed_error(e):
                    self._running = False
                    self.in_call = False
                    self._on_event("error", "The meeting browser was closed.")
                logger.exception("MeetBot xxx %s FALHOU", name)
                box.put((False, str(e)))

    @staticmethod
    def _is_browser_closed_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            "target page, context or browser has been closed" in msg
            or "targetclosederror" in msg
            or "browser has been closed" in msg
        )

    # DOM helpers.
    def _click_first(self, sels, timeout=8000) -> bool:
        for sel in sels:
            try:
                loc = self._page.locator(sel).first
                if loc.count() == 0:
                    continue                  # absent -> skip instantly (no timeout wait)
                loc.wait_for(state="visible", timeout=timeout)
                loc.click()
                return True
            except Exception:
                continue
        return False

    def _query_first(self, sels):
        for sel in sels:
            try:
                loc = self._page.locator(sel).first
                if loc.count() > 0 and loc.is_visible():
                    return loc
            except Exception:
                continue
        return None

    # Commands.
    # Locale-tolerant in-call detector. It first looks for hangup controls and
    # then falls back to call controls without lobby text.
    def _is_in_call(self) -> bool:
        try:
            return bool(self._page.evaluate(
                """() => {
                  const nodes = [...document.querySelectorAll('button,[role=button]')];
                  const hasLeave = nodes.some(b => {
                    const a = (b.getAttribute('aria-label')||'').toLowerCase();
                    const t = (b.innerText||'').toLowerCase();
                    return a.includes('leave call') || a.includes('sair da chamada')
                        || a.includes('end call') || a.includes('salir de la llamada')
                        || a.includes('abandonar') || (a.includes('sair') && a.includes('chamada'))
                        || t.includes('leave call') || t.includes('sair da chamada');
                  });
                  if (hasLeave) return true;

                  const body = (document.body?.innerText || '').toLowerCase();
                  const hasCallControls = nodes.some(b => {
                    const a = (b.getAttribute('aria-label')||'').toLowerCase();
                    return a.includes('chat') || a.includes('people')
                        || a.includes('pessoas') || a.includes('raise hand')
                        || a.includes('levantar a mao') || a.includes('levantar a mão');
                  });
                  const stillLobby = body.includes('ask to join')
                    || body.includes('request to join')
                    || body.includes('pedir para participar')
                    || body.includes('join now')
                    || body.includes('participar agora');
                  return hasCallControls && !stillLobby;
                }"""))
        except Exception:
            return False

    def _dump_buttons(self) -> list:
        try:
            return self._page.evaluate(
                """() => [...document.querySelectorAll('button,[role=button]')]
                     .map(b => b.getAttribute('aria-label'))
                     .filter(Boolean).slice(0, 60)""")
        except Exception:
            return []

    def _do_join(self, url: str):
        self._on_event("info", "Joining the meeting...")
        self._name_filled = False
        # If already in a call, do not navigate again.
        if self._is_in_call():
            self.in_call = True
            logger.info("join: already in call; skipping navigation")
            self._inject_tap()
            return "already in the meeting"
        logger.info("join: navigating to %s", url)
        self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self._page.wait_for_timeout(3000)
        logger.info("join: page loaded, url=%s", self._page.url)
        # Dismiss popups and turn camera/microphone off in the lobby.
        logger.info("join: dismiss popups=%s", self._click_first(S.DISMISS_POPUPS, timeout=2500))
        logger.info("join: cam off=%s", self._click_first(S.CAM_OFF, timeout=4000))
        logger.info("join: mic off=%s", self._click_first(S.MIC_OFF, timeout=4000))
        self.mic_muted = True
        # If Meet asks for a name (guest mode), fill it so "Ask to join" enables.
        self._fill_join_name()
        # Snapshot the lobby BEFORE clicking (page is alive for sure here).
        try:
            shots = Path(config.BASE_DIR) / "_ImagesPrj"
            shots.mkdir(exist_ok=True)
            self._page.screenshot(path=str(shots / "lobby_preclick.png"))
            logger.info("join: saved lobby_preclick.png (buttons: %s)", self._dump_buttons())
        except Exception as e:
            logger.warning("join: preclick snapshot failed: %s", e)
        # Best-effort join click. This does not decide success; _is_in_call does.
        clicked = (self._click_first(S.JOIN_NOW, timeout=2500)
                   or self._click_first(S.ASK_TO_JOIN, timeout=2500))
        logger.info("join: clicked join=%s", clicked)
        # Snapshot RIGHT NOW (page still alive) so we can see what Meet shows:
        # "asking to be let in", an error, a guest block, etc.
        try:
            shots = Path(config.BASE_DIR) / "_ImagesPrj"
            shots.mkdir(exist_ok=True)
            self._page.wait_for_timeout(500)
            self._page.screenshot(path=str(shots / "after_click.png"))
            logger.info("join: saved after_click.png (buttons: %s)", self._dump_buttons())
        except Exception as e:
            logger.warning("join: after_click snapshot failed: %s", e)
        self._on_event("info", "Please admit Jarvis into the meeting.")
        # Confirm by detecting the call screen for up to about 2 minutes.
        import time as _t
        deadline = _t.monotonic() + 120
        polls = 0
        while _t.monotonic() < deadline and not self.in_call:
            if self._is_in_call():
                self.in_call = True
                logger.info("join: entered call (JS detector) after %ds", polls)
                break
            if not clicked:
                self._fill_join_name()
                clicked = (self._click_first(S.JOIN_NOW, timeout=800)
                           or self._click_first(S.ASK_TO_JOIN, timeout=800))
                if clicked:
                    logger.info("join: clicked join (poll retry)")
            polls += 1
            if polls % 5 == 0:
                logger.info("join: waiting... %ds (url=%s)", polls, self._page.url)
            if polls == 8:
                # Early diagnostic snapshot so we can SEE the lobby/admission state.
                try:
                    shots = Path(config.BASE_DIR) / "_ImagesPrj"
                    shots.mkdir(exist_ok=True)
                    self._page.screenshot(path=str(shots / "lobby.png"))
                    logger.info("join: saved lobby.png (visible buttons: %s)", self._dump_buttons())
                except Exception:
                    pass
            self._page.wait_for_timeout(1000)
        if not self.in_call:
            # Diagnostics: dump visible buttons and save a screenshot.
            btns = self._dump_buttons()
            logger.warning("join: did not confirm within 120s. url=%s\n  VISIBLE BUTTONS: %s",
                           self._page.url, btns)
            try:
                shots = Path(config.BASE_DIR) / "_ImagesPrj"
                shots.mkdir(exist_ok=True)
                self._page.screenshot(path=str(shots / "join_fail.png"))
            except Exception:
                pass
            return "I clicked to join, but could not confirm admission. Ask the host to admit me and try again."
        # Start listening so the room can address Jarvis by name. Notes are only
        # DISPLAYED/STORED while active; outside notes it just watches for the name.
        if config.MEET_USE_CAPTIONS:
            # Preferred: read Google Meet's own captions (clean text). No audio tap.
            self._enable_captions()
            self._inject_captions()
        else:
            self._inject_tap()
            self._listener.start()
        forced = self._report_forced_mic()
        self._on_event("info", "Jarvis joined the meeting." +
                       (f" (meeting mic: {forced})" if forced else ""))
        return "joined the meeting"

    def _fill_join_name(self):
        """If Meet shows a guest 'Your name' field, fill it once with the bot name."""
        if getattr(self, "_name_filled", False):
            return
        name = (config.MEET_JOIN_NAME or "Jarvis").strip()
        box = self._query_first(S.NAME_INPUT)
        if box is None:
            return
        try:
            box.click()
            box.fill(name)
            self._name_filled = True
            logger.info("join: filled guest name=%r", name)
        except Exception as e:
            logger.warning("join: could not fill name: %s", e)

    def _enable_captions(self) -> bool:
        """Turn Meet captions ON. The call toolbar renders a moment after we are
        admitted, and the CC button may sit under 'More options', so we poll and
        fall back to the menu."""
        import time as _t
        deadline = _t.monotonic() + 12
        while _t.monotonic() < deadline:
            if self._query_first(S.CAPTIONS_OFF) is not None:
                logger.info("captions: already on")
                return True
            if self._click_first(S.CAPTIONS_ON, timeout=1500):
                logger.info("captions: turned on (toolbar)")
                return True
            self._page.wait_for_timeout(600)
        # Fallback: open the "More options" menu and enable captions there.
        try:
            if self._click_first(S.MORE_OPTIONS, timeout=2500):
                self._page.wait_for_timeout(800)
                if self._click_first(S.CAPTIONS_MENU_ITEM, timeout=2500):
                    logger.info("captions: turned on (more-options menu)")
                    return True
                self._page.keyboard.press("Escape")
        except Exception as e:
            logger.warning("captions: menu fallback failed: %s", e)
        logger.warning("captions: could NOT find the CC button to enable")
        return False

    def _inject_captions(self):
        if getattr(self, "_captions_injected", False):
            return
        try:
            self._page.evaluate(JS_CAPTIONS)
            self._captions_injected = True
            logger.info("captions: reader injected")
        except Exception as e:
            logger.warning("Failed to inject the caption reader: %s", e)

    def _report_forced_mic(self) -> str:
        """Read which device the getUserMedia override locked the mic to."""
        try:
            return self._page.evaluate("() => window.__jarvisMicForced || ''") or ""
        except Exception:
            return ""

    def _inject_tap(self):
        if self._tap_injected:
            return
        try:
            self._page.evaluate(JS_TAP)
            self._tap_injected = True
        except Exception as e:
            logger.warning("Failed to inject the audio tap: %s", e)

    def _set_mic_dom(self, muted: bool):
        """Set the Meet microphone state and confirm the DOM state changed."""
        desired = "muted" if muted else "unmuted"
        before = self._mic_state()
        logger.info("mic: before=%s desired=%s", before, desired)
        if before.get("state") == desired:
            return True

        clicked = self._click_mic_button(muted)
        if not clicked:
            # Official Meet shortcut on Windows. Fallback when the DOM changes.
            try:
                self._page.keyboard.press("Control+D")
                clicked = True
                logger.info("mic: fallback Control+D")
            except Exception:
                clicked = False
        if not clicked:
            logger.warning("mic: microphone control not found. state=%s", before)
            return False

        for _ in range(12):
            self._page.wait_for_timeout(250)
            after = self._mic_state()
            if after.get("state") == desired:
                logger.info("mic: after=%s", after)
                return True

        after = self._mic_state()
        logger.warning("mic: estado nao mudou para %s. after=%s", desired, after)
        return False

    def _mic_state(self) -> dict:
        try:
            return self._page.evaluate(
                """() => {
                  const controls = [...document.querySelectorAll('button,[role=button]')]
                    .map((b, index) => {
                      const aria = b.getAttribute('aria-label') || '';
                      const text = b.innerText || '';
                      const title = b.getAttribute('title') || '';
                      const all = `${aria} ${text} ${title}`.toLowerCase();
                      const rect = b.getBoundingClientRect();
                      return {
                        index, aria, text: text.trim(), title,
                        visible: !!(rect.width || rect.height || b.getClientRects().length),
                        x: Math.round(rect.x), y: Math.round(rect.y),
                        w: Math.round(rect.width), h: Math.round(rect.height),
                        all
                      };
                    })
                    .filter(b => b.visible && (
                      b.all.includes('microphone') || b.all.includes('microfone') ||
                      b.all.includes('mic') || b.all.includes('audio') ||
                      b.all.includes('áudio')
                    ));
                  const c = controls.find(b =>
                      b.all.includes('turn on microphone') ||
                      b.all.includes('turn off microphone') ||
                      b.all.includes('ativar microfone') ||
                      b.all.includes('desativar microfone') ||
                      b.all.includes('microphone') ||
                      b.all.includes('microfone')
                    ) || controls[0] || null;
                  if (!c) return { state: 'unknown', reason: 'no mic control', controls };
                  const s = c.all;
                  const unmuted = s.includes('turn off microphone') ||
                    s.includes('desativar microfone') ||
                    s.includes('desactivar micr') ||
                    s.includes('mute microphone') ||
                    s.includes('desligar microfone') ||
                    s.includes('microphone is on');
                  const muted = !unmuted && (
                    s.includes('turn on microphone') ||
                    s.includes('ativar microfone') ||
                    s.includes('activar micr') ||
                    s.includes('unmute') ||
                    s.includes('ligar microfone') ||
                    s.includes('microfone desativado') ||
                    s.includes('microphone is off')
                  );
                  return {
                    state: unmuted ? 'unmuted' : (muted ? 'muted' : 'unknown'),
                    control: { aria: c.aria, text: c.text, title: c.title, x: c.x, y: c.y, w: c.w, h: c.h },
                    controls: controls.slice(0, 12).map(b => ({ aria: b.aria, text: b.text, title: b.title, x: b.x, y: b.y, w: b.w, h: b.h }))
                  };
                }""")
        except Exception as e:
            return {"state": "unknown", "error": str(e)}

    def _click_mic_button(self, target_muted: bool | None = None) -> bool:
        try:
            return bool(self._page.evaluate(
                """(targetMuted) => {
                  const nodes = [...document.querySelectorAll('button,[role=button]')];
                  const candidates = nodes
                    .map((b) => {
                      const aria = b.getAttribute('aria-label') || '';
                      const text = b.innerText || '';
                      const title = b.getAttribute('title') || '';
                      const all = `${aria} ${text} ${title}`.toLowerCase();
                      const rect = b.getBoundingClientRect();
                      return { b, all, rect, visible: !!(rect.width || rect.height || b.getClientRects().length) };
                    })
                    .filter(x => x.visible && (
                      x.all.includes('microphone') || x.all.includes('microfone') ||
                      x.all.includes('mic')
                    ));
                  const wantsMute = targetMuted === true;
                  const wantsUnmute = targetMuted === false;
                  const isOpenControl = (x) =>
                    x.all.includes('turn on microphone') ||
                    (!x.all.includes('desativar microfone') && x.all.includes('ativar microfone')) ||
                    x.all.includes('activar micr') ||
                    x.all.includes('unmute');
                  const isMuteControl = (x) =>
                    x.all.includes('turn off microphone') ||
                    x.all.includes('desativar microfone') ||
                    x.all.includes('desactivar micr') ||
                    x.all.includes('mute microphone');
                  const target = (wantsUnmute ? candidates.find(isOpenControl) : null) ||
                    (wantsMute ? candidates.find(isMuteControl) : null) ||
                    candidates.find(x =>
                      isOpenControl(x) || isMuteControl(x)
                    ) || candidates[0];
                  if (!target) return false;
                  target.b.click();
                  return true;
                }""",
                target_muted))
        except Exception as e:
            logger.warning("mic: click JS falhou: %s", e)
            return False

    def _do_set_mic(self, muted: bool):
        ok = self._set_mic_dom(muted)
        if ok:
            self.mic_muted = muted
            return f"mic {'muted' if muted else 'unmuted'}"
        return f"could not {'mute' if muted else 'unmute'} the mic"

    def _do_speak(self, mp3: bytes):
        """Unmute if needed, speak through VB-CABLE, then restore the prior state."""
        if not self.in_call:
            logger.warning("speak: bot is not in the meeting; ignoring")
            return "I am not in the meeting yet"
        # Prevent Jarvis from treating its own meeting audio as a wake command,
        # and stop the listener from transcribing his own voice / its echo.
        self._room_command_suppressed_until = time.monotonic() + 120
        self._listener.suspend()
        was_muted = self.mic_muted
        logger.info("speak: was_muted=%s, mp3=%d bytes", was_muted, len(mp3 or b""))
        try:
            if was_muted:
                unmuted = self._set_mic_dom(False)
                logger.info("speak: unmute=%s", unmuted)
                if not unmuted:
                    return "could not unmute the meeting microphone"
                self.mic_muted = False
                self._page.wait_for_timeout(700)
            dur = audio_out.speak_pcm_to_cable(mp3)
            logger.info("speak: played %.1fs to VB-CABLE", dur)
            return "spoke in the meeting"
        finally:
            if was_muted:
                muted_ok = self._set_mic_dom(True)
                logger.info("speak: mute_back=%s", muted_ok)
                self.mic_muted = muted_ok
            self._page.wait_for_timeout(800)   # let the room echo of our voice pass
            self._listener.resume()
            # suspend() already swallowed the echo; keep only a tiny backup window
            # so it does not block the user's legitimate follow-up reply.
            self._room_command_suppressed_until = time.monotonic() + 0.5

    def _do_post_chat(self, text: str):
        if not self._click_first(S.CHAT_OPEN, timeout=6000):
            return "could not open the chat"
        self._page.wait_for_timeout(800)
        box = self._query_first(S.CHAT_INPUT)
        if box is None:
            return "could not find the chat message box"
        box.click()
        box.fill(text)
        if not self._click_first(S.CHAT_SEND, timeout=4000):
            box.press("Enter")          # fallback
        return "sent the chat message"

    def _do_start_notes(self):
        self.notes.start()
        if not config.MEET_USE_CAPTIONS:
            # Audio mode needs the tap + worker. In caption mode the reader is
            # already running since join, so do NOT touch captions here (clicking
            # again is slow and pointless).
            self._listener.start()
            self._inject_tap()
        return "notes started"

    def _do_stop_notes(self):
        # Only pause the minutes. Keep the listener running so the room can still
        # address Jarvis by name. (on_line is gated on notes.active, so the UI
        # stops showing notes immediately.)
        self.notes.stop()
        return "notes paused"

    def _do_leave(self):
        self._click_first(S.IN_CALL, timeout=4000)
        self._listener.stop()
        self.in_call = False
        return "left the meeting"

    def _do_screenshot(self, path: str):
        self._page.screenshot(path=path)
        return path

    def _on_note_line(self, text: str):
        self._on_event("note", text)

    def _on_meeting_command(self, text: str):
        if time.monotonic() < self._room_command_suppressed_until:
            logger.info("meeting command suppressed during Jarvis speech: %s", text)
            return
        logger.info("meeting command: %s", text)
        self._on_event("meeting_command", text)
