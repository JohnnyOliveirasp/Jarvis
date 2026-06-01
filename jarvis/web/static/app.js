// Cliente Jarvis: captura mic (com selecao de device + medidor de nivel),
// faz streaming PCM16 16k pro backend, toca a resposta e vibra a esfera.
// MAO-LIVRE: mic aberto, o VAD do backend detecta sua fala sozinho. Sem segurar nada.
(function () {
  const $ = (id) => document.getElementById(id);
  const statusEl = $('status'), logEl = $('log'), meterFill = $('meterFill');
  const micSelect = $('micSelect'), startBtn = $('startBtn'), talkBtn = $('talkBtn'),
        stopBtn = $('stopBtn'), joinBtn = $('joinBtn'), meetInput = $('meet');

  let ws = null, audioCtx = null, micStream = null, workletNode = null, srcNode = null,
      micAnalyser = null, playCtx = null, playAnalyser = null, speaking = false,
      sendMic = true,   // false enquanto Jarvis pensa/fala (evita ouvir a propria voz)
      paused = false;   // mute manual pelo usuario (botao)

  // ── Esfera: pega FFT da fala quando 'speaking' ──
  const freqBuf = () => {
    if (speaking && playAnalyser) {
      const a = new Uint8Array(playAnalyser.frequencyBinCount);
      playAnalyser.getByteFrequencyData(a);
      return a;
    }
    return null;
  };
  const orb = new Orb($('orb'), freqBuf);

  function setStatus(s) { statusEl.textContent = s; }
  function setOrb(s) { orb.setState(s); setStatus(s.toUpperCase()); }

  function addMsg(kind, who, text) {
    const d = document.createElement('div');
    d.className = 'msg ' + kind;
    d.innerHTML = (who ? `<span class="who">${who}</span>` : '') + (text || '');
    logEl.appendChild(d); logEl.scrollTop = logEl.scrollHeight;
  }

  // ── WebSocket ──
  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.binaryType = 'arraybuffer';
    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') {
        const m = JSON.parse(ev.data);
        if (m.type === 'state') {
          if (m.state === 'thinking' || m.state === 'speaking') sendMic = false;
          else if (m.state === 'idle' || m.state === 'listening') sendMic = true;
          if (!(speaking && m.state === 'idle')) setOrb(paused ? 'idle' : m.state);
        }
        else if (m.type === 'transcript') addMsg('you', 'VOCÊ', m.text);
        else if (m.type === 'reply') addMsg('jarvis', 'JARVIS', m.text);
        else if (m.type === 'info') addMsg('info', '', m.text);
        else if (m.type === 'error') addMsg('info', 'ERRO', m.message);
      } else {
        playReply(ev.data); // ArrayBuffer = mp3 da voz
      }
    };
    ws.onclose = () => { setStatus('DESCONECTADO'); };
  }

  // ── Toca a resposta + alimenta a esfera (vibra) ──
  async function playReply(arrayBuf) {
    if (!playCtx) playCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (!playAnalyser) { playAnalyser = playCtx.createAnalyser(); playAnalyser.fftSize = 256; }
    try {
      const buf = await playCtx.decodeAudioData(arrayBuf.slice(0));
      const src = playCtx.createBufferSource();
      src.buffer = buf;
      src.connect(playAnalyser); playAnalyser.connect(playCtx.destination);
      speaking = true; setOrb('speaking');
      src.onended = () => { speaking = false; sendMic = true; setOrb(paused ? 'idle' : 'idle'); };
      src.start();
    } catch (e) {
      sendMic = true;
      addMsg('info', 'ERRO', 'Falha ao tocar audio: ' + e.message);
    }
  }

  // ── Microfone: lista devices + medidor de nivel ──
  async function listMics() {
    const devs = await navigator.mediaDevices.enumerateDevices();
    const mics = devs.filter(d => d.kind === 'audioinput');
    micSelect.innerHTML = '';
    mics.forEach((d, i) => {
      const o = document.createElement('option');
      o.value = d.deviceId; o.textContent = d.label || `Microfone ${i + 1}`;
      micSelect.appendChild(o);
    });
  }

  async function startMic() {
    const deviceId = micSelect.value || undefined;
    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: deviceId ? { exact: deviceId } : undefined,
                 echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) { addMsg('info', 'ERRO', 'Microfone negado/indisponivel: ' + e.message); return; }

    await listMics(); // agora com labels (permissao concedida)

    audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    if (audioCtx.state === 'suspended') await audioCtx.resume();
    await audioCtx.audioWorklet.addModule('/static/pcm-worklet.js');

    srcNode = audioCtx.createMediaStreamSource(micStream);

    // medidor de nivel (analyser separado)
    micAnalyser = audioCtx.createAnalyser(); micAnalyser.fftSize = 512;
    srcNode.connect(micAnalyser);
    drawMeter();

    // worklet -> PCM16 -> WebSocket (so quando NAO esta pausado e Jarvis nao fala)
    workletNode = new AudioWorkletNode(audioCtx, 'pcm-worklet');
    workletNode.port.onmessage = (ev) => {
      if (sendMic && !paused && ws && ws.readyState === WebSocket.OPEN) ws.send(ev.data);
    };
    srcNode.connect(workletNode);
    const sink = audioCtx.createGain(); sink.gain.value = 0;
    workletNode.connect(sink); sink.connect(audioCtx.destination);

    connectWS();
    startBtn.disabled = true; talkBtn.disabled = false; stopBtn.disabled = false;
    paused = false; talkBtn.classList.remove('primary'); talkBtn.textContent = '⏸ Pausar escuta';
    addMsg('info', '', 'Microfone conectado: ' + (micSelect.options[micSelect.selectedIndex]?.text || '?') + ' — pode falar, estou ouvindo.');
  }

  function drawMeter() {
    if (!micAnalyser) return;
    const a = new Uint8Array(micAnalyser.fftSize);
    micAnalyser.getByteTimeDomainData(a);
    let peak = 0;
    for (let i = 0; i < a.length; i++) peak = Math.max(peak, Math.abs(a[i] - 128));
    const pct = Math.min(100, (peak / 128) * 180); // amplifica p/ visualizar
    meterFill.style.width = (paused ? 0 : pct) + '%';
    requestAnimationFrame(drawMeter);
  }

  function stopMic() {
    if (workletNode) workletNode.disconnect();
    if (srcNode) srcNode.disconnect();
    if (micStream) micStream.getTracks().forEach(t => t.stop());
    if (audioCtx) audioCtx.close();
    if (ws) ws.close();
    audioCtx = micStream = workletNode = srcNode = micAnalyser = null;
    sendMic = true; paused = false;
    meterFill.style.width = '0%';
    talkBtn.classList.remove('primary'); talkBtn.textContent = '⏸ Pausar escuta';
    startBtn.disabled = false; talkBtn.disabled = true; stopBtn.disabled = true;
    setStatus('DESCONECTADO');
  }

  // ── Botoes ──
  startBtn.onclick = startMic;
  stopBtn.onclick = stopMic;

  // Pausar/Retomar a escuta (mute manual — util em reuniao).
  talkBtn.onclick = () => {
    paused = !paused;
    if (paused) {
      talkBtn.classList.add('primary');
      talkBtn.textContent = '▶ Retomar escuta';
      setStatus('PAUSADO');
      addMsg('info', '', 'Escuta pausada. Clique em "Retomar" pra ele voltar a ouvir.');
    } else {
      talkBtn.classList.remove('primary');
      talkBtn.textContent = '⏸ Pausar escuta';
      setStatus('ESCUTANDO');
    }
  };

  micSelect.onchange = () => { if (audioCtx) { stopMic(); startMic(); } };
  joinBtn.onclick = () => {
    const url = meetInput.value.trim();
    if (!url) return;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'set_meet', url }));
    window.open(url, '_blank');
    addMsg('info', '', 'Abrindo a reunião... (o ingresso automático do bot é a próxima fase)');
  };

  // popula a lista de mics ja no load (labels aparecem apos permitir)
  navigator.mediaDevices.enumerateDevices().then(listMics).catch(() => {});
})();
