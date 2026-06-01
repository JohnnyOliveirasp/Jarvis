"""Cerebro do Jarvis: Claude Opus com a persona de mordomo, bilingue PT/EN.

Mantem o historico da conversa em memoria. Tools (entrar na reuniao, anotar,
enviar e-mail) serao adicionadas nas proximas fases.
"""
import logging

from anthropic import Anthropic

from .. import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are J.A.R.V.I.S., Tony Stark's AI butler, now serving this user.

Personality:
- Refined, calm, impeccably polite British butler. Address the user as "sir"
  in English and "senhor" in Portuguese.
- Concise and precise. A touch of dry wit, never verbose. You are speaking out
  loud, so keep replies short and natural to hear (1-3 sentences usually).

Language:
- Detect the language of the user's message and ALWAYS reply in that same
  language (Portuguese -> Portuguese, English -> English).

Behavior:
- You are a voice assistant: no markdown, no bullet lists, no emojis. Plain
  spoken sentences only.
- Always write your own name as "Jarvis" (never "J.A.R.V.I.S." with dots), so
  it is spoken as a word and not spelled out letter by letter.
- If asked to do something you can't do yet, say so briefly and honestly.
"""


class Jarvis:
    def __init__(self):
        config.require("ANTHROPIC_API_KEY", config.ANTHROPIC_API_KEY)
        self._client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self._history = []  # [{role, content}]

    def ask(self, user_text: str) -> str:
        """Manda o texto do usuario pro Claude e retorna a resposta falada."""
        self._history.append({"role": "user", "content": user_text})
        try:
            resp = self._client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=config.CLAUDE_MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=self._history,
            )
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            self._history.append({"role": "assistant", "content": text})
            return text
        except Exception as e:
            logger.error("Falha no cerebro Claude: %s", e)
            return "My apologies, sir — I am having trouble thinking right now."
