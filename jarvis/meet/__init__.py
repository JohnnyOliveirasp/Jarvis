"""Bot do Google Meet do Jarvis (Playwright, perfil Chrome persistente).

Sub-modulos:
  selectors  - seletores DOM do Meet centralizados (a parte que mais quebra)
  audio_out  - toca a voz do Jarvis no microfone virtual (VB-CABLE)
  listener   - "grampeia" o audio dos participantes no proprio browser -> Whisper
  notes      - acumula a ata e resume via Claude
  bot        - MeetBot: thread dedicada que dirige o Chrome (entrar/falar/mutar/chat)
"""
