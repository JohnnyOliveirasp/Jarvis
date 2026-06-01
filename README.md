# J.A.R.V.I.S.

Assistente de voz pessoal estilo Homem de Ferro, com a **voz real do filme** (clone ElevenLabs), cérebro **Claude Opus** e wake word mãos-livres.

## Status — Fase 1 (núcleo de voz)
- ✅ Wake word "Hey Jarvis" (mãos-livres, openWakeWord)
- ✅ Comando por voz → transcrição (Groq Whisper)
- ✅ Cérebro Claude Opus (persona mordomo, bilíngue PT/EN)
- ✅ Resposta na voz clonada do filme (ElevenLabs streaming)
- 🔜 Fase 2: reunião (entrar no Meet, anotar ata, falar quando chamado)

## Rodar (Windows / PowerShell)
```powershell
# 1) venv
.\venv_Jarvis\Scripts\activate

# 2) (primeira vez) instalar deps
pip install -r requirements.txt

# 3) rodar
python -m jarvis.main
```
Diga **"Hey Jarvis"** → aguarde o "Yes, sir?" → fale seu comando.

## Pré-requisitos
- Python 3.11+
- ffmpeg/ffplay no PATH (reprodução de áudio)
- Microfone

## Estrutura
```
jarvis/
  config.py        # .env + constantes
  audio.py         # mic: wake word + gravação do comando
  voice/stt.py     # transcrição (Groq Whisper)
  voice/tts.py     # voz do Jarvis (ElevenLabs streaming)
  core/brain.py    # cérebro Claude Opus (persona)
  main.py          # loop principal
scripts/           # utilitários (clone de voz, consolidação .env)
```

> Voz: clone para **uso pessoal** da voz do J.A.R.V.I.S. (Paul Bettany). Não usar comercialmente.
