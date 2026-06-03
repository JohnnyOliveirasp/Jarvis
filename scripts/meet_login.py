"""Login UNICO no Google para o bot do Meet (perfil Chrome persistente).

Roda uma vez. Abre um Chrome controlado pela Playwright usando a MESMA pasta de
perfil que o bot vai usar (config.MEET_USER_DATA_DIR). Voce:
  1. Faz login na sua conta Google (resolve 2FA/captcha normalmente, na mao).
  2. (RECOMENDADO) Abre meet.google.com -> inicie/entre numa reuniao de teste ->
     nas configuracoes de audio, escolha "CABLE Output (VB-Audio Virtual Cable)"
     como MICROFONE. O perfil memoriza essa escolha — e assim a reuniao ouve a
     voz do Jarvis (que tocamos no "CABLE Input").
  3. Volte ao terminal e tecle ENTER pra fechar e salvar a sessao.

Depois disso, o bot entra logado sem pedir senha de novo.

Rodar (PowerShell):
  .\venv_Jarvis\Scripts\activate
  python -m scripts.meet_login
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import config  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402


def main():
    print("=" * 64)
    print("LOGIN DO BOT DO MEET — perfil:", config.MEET_USER_DATA_DIR)
    print("Conta default do bot:", config.MEET_BOT_EMAIL)
    print("=" * 64)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=config.MEET_USER_DATA_DIR,
            channel=config.MEET_BROWSER_CHANNEL,   # Chrome real (codecs do Meet)
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            no_viewport=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://accounts.google.com/")
        print("\n>> Faça login na sua conta Google na janela que abriu.")
        print(">> Conta planejada:", config.MEET_BOT_EMAIL)
        print(">> Depois, abra meet.google.com e escolha 'CABLE Output' como microfone")
        print("   numa reunião de teste (o perfil memoriza).")
        print("\n>> Quando terminar, volte aqui e tecle ENTER para salvar e fechar.")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        try:
            ctx.close()
        except Exception:
            pass  # navegador ja fechado na mao — sessao ja foi salva no disco
    print("Sessão salva. O bot agora entra logado. ✔")


if __name__ == "__main__":
    main()
