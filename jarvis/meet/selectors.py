"""Seletores DOM do Google Meet — CENTRALIZADOS de proposito.

A pesquisa (2026-06-02, ver memoria reference-meet-bot-research) foi enfatica:
os seletores do Meet sao a MAIOR fonte de quebra. O Google troca classes e
layout a qualquer momento. Regras:
  - Preferir aria-label por SUBSTRING (*=) e nunca classes obfuscadas.
  - Cada acao tem VARIAS alternativas (pt-BR e en) tentadas em ordem.
  - Se algo quebrar, conserta-se SO aqui.

Atalhos de teclado do Meet (Windows) — mais estaveis que clicar:
  Ctrl+D = liga/desliga microfone   |   Ctrl+E = liga/desliga camera
"""

# Botoes de mic/camera na ante-sala E dentro da chamada (substring, bilingue).
MIC_OFF = [
    'button[aria-label*="Turn off microphone" i]',
    'button[aria-label*="Desativar microfone" i]',
    'div[role="button"][aria-label*="microfone" i][aria-label*="Desativar" i]',
]
CAM_OFF = [
    'button[aria-label*="Turn off camera" i]',
    'button[aria-label*="Desativar câmera" i]',
    'div[role="button"][aria-label*="câmera" i][aria-label*="Desativar" i]',
]

# Popups que aparecem antes de entrar ("Got it" / "Entendi", etc.)
DISMISS_POPUPS = [
    'button:has-text("Got it")',
    'button:has-text("Entendi")',
    'button:has-text("OK")',
    'button[aria-label="Close" i]',
]

# Campo "Seu nome" que o Meet pede no modo CONVIDADO (antes do Ask to join).
NAME_INPUT = [
    'input[aria-label*="Your name" i]',
    'input[aria-label*="Seu nome" i]',
    'input[placeholder*="Your name" i]',
    'input[placeholder*="seu nome" i]',
    'input[placeholder*="name" i]',
    'input[placeholder*="nome" i]',
]

# Botao de entrar — varia: "Join now" / "Participar agora" / "Ask to join" / "Pedir para participar".
JOIN_NOW = [
    'button:has-text("Participar agora")',
    'button:has-text("Join now")',
    'span:has-text("Participar agora")',
    'span:has-text("Join now")',
]
ASK_TO_JOIN = [
    'button:has-text("Pedir para participar")',
    'button:has-text("Ask to join")',
    'span:has-text("Pedir para participar")',
    'span:has-text("Ask to join")',
]

# Confirma que ENTROU de fato (passou da ante-sala/admissao): aparece o botao de
# encerrar ("Leave call"/"Sair da chamada"). Aceita qualquer tag (button OU
# div[role=button]) — no Meet atual costuma ser um <button>, mas variamos por seguranca.
IN_CALL = [
    '[aria-label*="Leave call" i]',
    '[aria-label*="Sair da chamada" i]',
    'button[jsname][aria-label*="call" i]',
]

# Ligar legendas (CC). So clicamos no botao no estado "desligado"
# ("Turn on captions"/"Ativar legendas") pra nao desligar sem querer.
CAPTIONS_ON = [
    'button[aria-label*="Turn on captions" i]',
    'button[aria-label*="Ativar legendas" i]',
    'button[aria-label*="Ativar as legendas" i]',
    'button[aria-label*="Turn on caption" i]',
    'button[aria-label*="closed captions" i][aria-label*="on" i]',
    'div[role="button"][aria-label*="Turn on captions" i]',
    'div[role="button"][aria-label*="Ativar legendas" i]',
]
# Legendas JA ligadas (estado "desligar") — usado so pra detectar que ja estao on.
CAPTIONS_OFF = [
    'button[aria-label*="Turn off captions" i]',
    'button[aria-label*="Desativar legendas" i]',
    'button[aria-label*="Desativar as legendas" i]',
    'div[role="button"][aria-label*="Turn off captions" i]',
    'div[role="button"][aria-label*="Desativar legendas" i]',
]
# Menu "Mais opcoes" (3 pontinhos) e o item de legendas dentro dele (fallback).
MORE_OPTIONS = [
    'button[aria-label*="More options" i]',
    'button[aria-label*="Mais opções" i]',
    'button[aria-label*="Mais opções" i]',
]
CAPTIONS_MENU_ITEM = [
    '[role="menuitem"][aria-label*="captions" i]',
    '[role="menuitem"][aria-label*="legendas" i]',
    '[role="menuitem"]:has-text("Turn on captions")',
    '[role="menuitem"]:has-text("Ativar legendas")',
    '[role="menuitem"]:has-text("legendas")',
    '[role="menuitem"]:has-text("captions")',
]

# Chat dentro da reuniao.
CHAT_OPEN = [
    'button[aria-label*="Chat with everyone" i]',
    'button[aria-label*="Chat com todos" i]',
    'button[aria-label*="mensagens" i]',
]
CHAT_INPUT = [
    'textarea[aria-label*="Send a message" i]',
    'textarea[aria-label*="Enviar uma mensagem" i]',
    'textarea[placeholder*="mensagem" i]',
    'textarea[placeholder*="message" i]',
]
CHAT_SEND = [
    'button[aria-label*="Send a message" i]',
    'button[aria-label*="Enviar mensagem" i]',
    'button[aria-label*="Send" i]',
]
