"""Loop principal do Jarvis (Fase 1): mao-livre por voz.

Fluxo:  [espera "Hey Jarvis"]  ->  grava comando  ->  transcreve  ->
        Claude pensa  ->  responde na voz do filme  ->  repete.

Rode com:  python -m jarvis.main
"""
import logging

from . import audio
from .voice import stt, tts
from .core.brain import Jarvis


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    setup_logging()
    log = logging.getLogger("jarvis")

    jarvis = Jarvis()
    log.info("J.A.R.V.I.S. online. Diga 'Hey Jarvis' para acordar.")
    tts.speak("J.A.R.V.I.S. online and at your service, sir.")

    while True:
        try:
            # Acorda na wake word + captura o comando no MESMO stream (com bip).
            pcm = audio.listen_and_capture()
            user_text = stt.transcribe(pcm)
            if not user_text:
                tts.speak("I didn't catch that, sir.")
                continue

            log.info("Voce: %s", user_text)
            reply = jarvis.ask(user_text)
            log.info("Jarvis: %s", reply)
            tts.speak(reply)

        except KeyboardInterrupt:
            log.info("Encerrando. Goodbye, sir.")
            break
        except Exception as e:
            log.exception("Erro no loop: %s", e)


if __name__ == "__main__":
    main()
