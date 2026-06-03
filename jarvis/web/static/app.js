// Jarvis client: captures microphone audio, streams PCM16 16 kHz to the backend,
// plays the reply, and drives the orb visualization.
// Hands-free: the backend VAD detects speech without push-to-talk.
(function () {
  const $ = (id) => document.getElementById(id);
  const statusEl = $('status'), logEl = $('log'), meterFill = $('meterFill');
  const micSelect = $('micSelect'), startBtn = $('startBtn'), talkBtn = $('talkBtn'),
        stopBtn = $('stopBtn'), joinBtn = $('joinBtn'), meetInput = $('meet');

  let ws = null, audioCtx = null, micStream = null, workletNode = null, srcNode = null,
      micAnalyser = null, playCtx = null, playAnalyser = null, speaking = false,
      sendMic = true,   // false while Jarvis thinks/speaks, avoiding self-capture
      paused = false;   // manual listening pause

  // Orb: use playback FFT while speaking.
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
        else if (m.type === 'transcript') addMsg('you', 'YOU', m.text);
        else if (m.type === 'reply') addMsg('jarvis', 'JARVIS', m.text);
        else if (m.type === 'meet') addMsg('meet', 'MEETING', m.text);
        else if (m.type === 'note') addMsg('note', 'NOTES', m.text);
        else if (m.type === 'info') addMsg('info', '', m.text);
        else if (m.type === 'error') addMsg('info', 'ERROR', m.message);
      } else {
        playReply(ev.data); // ArrayBuffer = MP3 voice reply.
      }
    };
    ws.onclose = () => { setStatus('DISCONNECTED'); };
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
      src.onended = () => { speaking = false; sendMic = true; setOrb('idle'); };
      src.start();
    } catch (e) {
      sendMic = true;
      addMsg('info', 'ERROR', 'Failed to play audio: ' + e.message);
    }
  }

  // Microphone list and level meter.
  async function listMics() {
    const devs = await navigator.mediaDevices.enumerateDevices();
    const mics = devs.filter(d => d.kind === 'audioinput');
    micSelect.innerHTML = '';
    mics.forEach((d, i) => {
      const o = document.createElement('option');
      o.value = d.deviceId; o.textContent = d.label || `Microphone ${i + 1}`;
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
    } catch (e) { addMsg('info', 'ERROR', 'Microphone denied or unavailable: ' + e.message); return; }

    await listMics(); // Labels are available after permission is granted.

    audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    if (audioCtx.state === 'suspended') await audioCtx.resume();
    await audioCtx.audioWorklet.addModule('/static/pcm-worklet.js');

    srcNode = audioCtx.createMediaStreamSource(micStream);

    // Level meter.
    micAnalyser = audioCtx.createAnalyser(); micAnalyser.fftSize = 512;
    srcNode.connect(micAnalyser);
    drawMeter();

    // worklet -> PCM16 -> WebSocket, only when not paused and Jarvis is not speaking.
    workletNode = new AudioWorkletNode(audioCtx, 'pcm-worklet');
    workletNode.port.onmessage = (ev) => {
      if (sendMic && !paused && ws && ws.readyState === WebSocket.OPEN) ws.send(ev.data);
    };
    srcNode.connect(workletNode);
    const sink = audioCtx.createGain(); sink.gain.value = 0;
    workletNode.connect(sink); sink.connect(audioCtx.destination);

    connectWS();
    startBtn.disabled = true; talkBtn.disabled = false; stopBtn.disabled = false;
    paused = false; talkBtn.classList.remove('primary'); talkBtn.textContent = 'Pause listening';
    addMsg('info', '', 'Microphone connected: ' + (micSelect.options[micSelect.selectedIndex]?.text || '?') + ' — you may speak.');
  }

  function drawMeter() {
    if (!micAnalyser) return;
    const a = new Uint8Array(micAnalyser.fftSize);
    micAnalyser.getByteTimeDomainData(a);
    let peak = 0;
    for (let i = 0; i < a.length; i++) peak = Math.max(peak, Math.abs(a[i] - 128));
    const pct = Math.min(100, (peak / 128) * 180); // Amplify for visualization.
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
    talkBtn.classList.remove('primary'); talkBtn.textContent = 'Pause listening';
    startBtn.disabled = false; talkBtn.disabled = true; stopBtn.disabled = true;
    setStatus('DISCONNECTED');
  }

  // ── Botoes ──
  startBtn.onclick = startMic;
  stopBtn.onclick = stopMic;

  // Pause/resume listening.
  talkBtn.onclick = () => {
    paused = !paused;
    if (paused) {
      talkBtn.classList.add('primary');
      talkBtn.textContent = 'Resume listening';
      setStatus('PAUSED');
      addMsg('info', '', 'Listening paused. Click resume to let Jarvis hear you again.');
    } else {
      talkBtn.classList.remove('primary');
      talkBtn.textContent = 'Pause listening';
      setStatus('LISTENING');
    }
  };

  micSelect.onchange = () => { if (audioCtx) { stopMic(); startMic(); } };
  joinBtn.onclick = () => {
    const url = meetInput.value.trim();
    if (!url) { addMsg('info', '', 'Paste the Google Meet link first.'); return; }
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      addMsg('info', '', 'Connect the microphone first.');
      return;
    }
    ws.send(JSON.stringify({ type: 'join_meet', url }));
    addMsg('meet', 'MEETING', 'Link saved. Say “Jarvis, enter the meeting” to join.');
  };

  // Populate microphone list on load. Labels appear after permission is granted.
  navigator.mediaDevices.enumerateDevices().then(listMics).catch(() => {});
})();
