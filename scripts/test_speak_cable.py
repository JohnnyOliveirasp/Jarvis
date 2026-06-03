"""Testa SO o caminho de audio da fala: voz do Jarvis -> VB-CABLE (CABLE Input).

Com o bot UNMUTADO na reuniao (mic = CABLE Output), rode isto: a sala deve
OUVIR a frase, e a exclamacao "ninguem te ouve" some durante a fala.

Uso:
  python -m scripts.test_speak_cable
  python -m scripts.test_speak_cable "Boa noite a todos, aqui e o Jarvis."
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import config            # noqa: E402
from jarvis.voice import tts          # noqa: E402
from jarvis.meet import audio_out     # noqa: E402


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "Boa noite a todos. Aqui é o Jarvis, ao seu dispor."
    dev = audio_out.find_output_device(config.MEET_SPEAK_DEVICE)
    print(f">> Dispositivo de saida '{config.MEET_SPEAK_DEVICE}': idx={dev}")
    print(f">> Sintetizando: {text!r}")
    mp3 = tts.synthesize(text)
    print(f">> mp3: {len(mp3)} bytes")
    if not mp3:
        print(">> FALHA: ElevenLabs nao retornou audio.")
        return
    dur = audio_out.speak_pcm_to_cable(mp3)
    print(f">> Toquei {dur:.1f}s no CABLE Input. A sala ouviu?")


if __name__ == "__main__":
    main()
