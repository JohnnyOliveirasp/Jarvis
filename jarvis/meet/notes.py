"""Ata da reuniao: acumula as falas transcritas e resume via Claude.

O listener joga linhas de transcricao aqui (thread-safe). Quando o usuario
pede ("ok Jarvis, terminou as anotacoes"), o Jarvis chama summary() para gerar
uma ata curta e mandar no chat do Meet.
"""
import logging
import threading

from anthropic import Anthropic

from .. import config

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = """\
You are Jarvis, the user's meeting assistant. You receive a raw transcript that \
may contain speech-recognition noise. Produce concise meeting notes in plain \
text, with no markdown. Use the predominant language of the transcript. If the \
meeting is multilingual, use the language most useful to the user based on the \
transcript.

Include:
- A short summary, 2 to 5 lines.
- Decisions, if any.
- Action items / pending items, including owners when they can be inferred.

Be concise and faithful. Do not invent anything. If the transcript is empty or \
not useful, answer in the transcript language with the equivalent of: \
"There was not enough useful content for meeting notes."
"""


class MeetingNotes:
    def __init__(self):
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self.active = False
        self._client = Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def start(self):
        with self._lock:
            self._lines.clear()
            self.active = True
        logger.info("Ata iniciada.")

    def stop(self):
        self.active = False
        logger.info("Ata pausada.")

    def add_line(self, text: str):
        text = (text or "").strip()
        if not text or not self.active:
            return
        with self._lock:
            self._lines.append(text)

    @property
    def transcript(self) -> str:
        with self._lock:
            return "\n".join(self._lines)

    def summary(self) -> str:
        raw = self.transcript
        if not raw.strip():
            return "Nao houve conteudo suficiente para uma ata."
        try:
            resp = self._client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=700,
                system=_SUMMARY_PROMPT,
                messages=[{"role": "user", "content": raw}],
            )
            return "".join(b.text for b in resp.content if b.type == "text").strip()
        except Exception as e:
            logger.error("Falha ao resumir a ata: %s", e)
            # fallback: manda a transcricao crua (cortada) se o resumo falhar
            return "Ata (bruta):\n" + raw[:1500]
