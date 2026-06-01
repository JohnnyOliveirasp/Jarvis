"""Teste headless (sem microfone): valida cerebro Claude + voz clonada do filme."""
import logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")

from jarvis.core.brain import Jarvis
from jarvis.voice import tts

j = Jarvis()

print("\n[1/2] Teste em INGLES...")
r1 = j.ask("Jarvis, introduce yourself in one short sentence.")
print("Jarvis:", r1)
tts.speak(r1)

print("\n[2/2] Teste em PORTUGUES...")
r2 = j.ask("Jarvis, diga em portugues, em uma frase, que voce esta pronto para entrar na reuniao.")
print("Jarvis:", r2)
tts.speak(r2)

print("\nOK — cerebro + voz funcionando.")
