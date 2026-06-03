"""Teste DEFINITIVO do VB-CABLE: o cabo passa audio? (sem depender do Meet)

Toca a voz no 'CABLE Input' e grava do 'CABLE Output' ao mesmo tempo. Se o RMS
gravado for alto -> o cabo funciona (problema esta no mute do Meet). Se for ~0 ->
o 'CABLE Output' esta mudo/desativado no Windows.
"""
import sys
from pathlib import Path

import numpy as np
import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.voice import tts          # noqa: E402
from jarvis.meet import audio_out     # noqa: E402

RATE = 48000


def find_input(name):
    for i, d in enumerate(sd.query_devices()):
        if name.lower() in d["name"].lower() and d["max_input_channels"] > 0:
            return i
    return None


def main():
    out_dev = audio_out.find_output_device("CABLE Input")    # tocar aqui
    in_dev = find_input("CABLE Output")                       # gravar daqui
    print(f">> tocar  -> CABLE Input  idx={out_dev}")
    print(f">> gravar <- CABLE Output idx={in_dev}")
    if out_dev is None or in_dev is None:
        print(">> FALHA: dispositivo VB-CABLE nao encontrado.")
        return

    mp3 = tts.synthesize("Teste de áudio do Jarvis. Um, dois, três.")
    data = audio_out._mp3_to_pcm(mp3, RATE)
    if data.size == 0:
        print(">> FALHA: TTS vazio.")
        return
    data = data.reshape(-1, 1)
    print(f">> tocando+gravando {data.size / RATE:.1f}s...")
    rec = sd.playrec(data, samplerate=RATE, channels=1,
                     device=(in_dev, out_dev), dtype="float32")
    sd.wait()
    rms = float(np.sqrt(np.mean(rec.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(rec)))
    print(f">> RMS gravado = {rms:.5f} | pico = {peak:.5f}")
    if rms > 0.005:
        print(">> ✅ O CABO PASSA AUDIO. Problema esta no mute do Meet (mic do bot).")
    else:
        print(">> ❌ CABO MUDO. 'CABLE Output' esta mutado/desativado no Windows (Gravacao).")


if __name__ == "__main__":
    main()
