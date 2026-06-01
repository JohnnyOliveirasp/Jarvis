// Esfera J.A.R.V.I.S. — port do AudioOrb (canvas 2D, reativa ao audio).
// Estados: idle | listening | thinking | speaking. Vibra com a voz (FFT/RMS).
(function () {
  const W = 380, H = 440, CX = W / 2, CY = 200, R = 92;

  // grade de pontos da esfera (lat x long), pre-computada
  const DOTS = [];
  const LAT = 14, LONG = 22;
  for (let i = 1; i < LAT; i++) {
    const lat = (i / LAT) * Math.PI - Math.PI / 2;
    for (let j = 0; j < LONG; j++) {
      const lng = (j / LONG) * Math.PI * 2;
      const x = Math.cos(lat) * Math.sin(lng);
      const y = Math.sin(lat);
      const z = Math.cos(lat) * Math.cos(lng);
      const band = Math.floor(((Math.atan2(y, x) + Math.PI) / (2 * Math.PI)) * 32);
      DOTS.push({ x, y, z, band });
    }
  }

  function statusLabel(s) {
    return ({ idle: 'STANDBY', listening: 'LISTENING', thinking: 'PROCESSING', speaking: 'SPEAKING' }[s] || '');
  }

  class Orb {
    constructor(canvas, getFreq) {
      this.ctx = canvas.getContext('2d');
      this.getFreq = getFreq; // () => Uint8Array | null
      this.state = 'idle';
      this.t = 0;
      this._loop = this._loop.bind(this);
      requestAnimationFrame(this._loop);
    }
    setState(s) { this.state = s; }

    _loop() {
      this.t += 1 / 60;
      const ctx = this.ctx, t = this.t, s = this.state;
      const data = this.getFreq ? this.getFreq() : null;
      let rms = 0;
      if (data) { let sum = 0; for (let i = 0; i < data.length; i++) sum += data[i]; rms = sum / data.length / 255; }

      ctx.clearRect(0, 0, W, H);
      this._frame(ctx);
      this._label(ctx, s);
      this._glow(ctx, t, s, rms);
      this._rings(ctx, t, s);
      this._sphere(ctx, t, s, rms, data);
      this._eq(ctx, data, s);
      requestAnimationFrame(this._loop);
    }

    _frame(ctx) {
      ctx.strokeStyle = 'rgba(0,191,255,.5)'; ctx.lineWidth = 1.5;
      const L = 20, m = 10;
      const corners = [[m, m, 1, 1], [W - m, m, -1, 1], [m, H - m, 1, -1], [W - m, H - m, -1, -1]];
      for (const [x, y, dx, dy] of corners) {
        ctx.beginPath();
        ctx.moveTo(x, y + dy * L); ctx.lineTo(x, y); ctx.lineTo(x + dx * L, y);
        ctx.stroke();
      }
    }
    _label(ctx, s) {
      ctx.textAlign = 'center';
      ctx.font = '10px "Courier New",monospace';
      ctx.fillStyle = 'rgba(0,191,255,.8)';
      ctx.fillText('· J A R V I S · CORE · v1.0 ·', CX, 30);
      ctx.font = 'bold 12px "Courier New",monospace';
      ctx.fillStyle = 'rgba(0,220,255,.95)';
      ctx.fillText(statusLabel(s), CX, 322);
    }
    _glow(ctx, t, s, rms) {
      const gr = R + 42 + (s === 'speaking' ? rms * 34 : 0) + Math.sin(t * 1.5) * 5;
      const a = s === 'idle' ? .04 : s === 'listening' ? .09 + Math.sin(t * 2) * .03
        : s === 'speaking' ? .18 + rms * .25 : s === 'thinking' ? .11 : .05;
      const g = ctx.createRadialGradient(CX, CY, 0, CX, CY, gr);
      g.addColorStop(0, `rgba(0,191,255,${a})`);
      g.addColorStop(.5, `rgba(0,191,255,${a * .4})`);
      g.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = g; ctx.fillRect(CX - gr, CY - gr, gr * 2, gr * 2);
    }
    _rings(ctx, t, s) {
      const n = (s === 'speaking' || s === 'thinking') ? 3 : 1;
      const cfg = [
        { r: R + 14, tilt: .4, sp: .4, a: .5 },
        { r: R + 34, tilt: -.7, sp: .6, a: .35 },
        { r: R + 56, tilt: .9, sp: .3, a: .22 },
      ];
      for (let i = 0; i < n; i++) {
        const c = cfg[i];
        ctx.save(); ctx.translate(CX, CY); ctx.rotate(t * c.sp * (i % 2 ? -1 : 1));
        const yr = Math.abs(c.r * Math.cos(c.tilt + Math.sin(t * .3) * .08));
        ctx.beginPath(); ctx.ellipse(0, 0, c.r, yr, 0, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(0,191,255,${c.a})`; ctx.lineWidth = 1; ctx.stroke();
        if (s === 'speaking' || s === 'thinking') {
          const ang = t * c.sp * 2, dx = Math.cos(ang) * c.r, dy = Math.sin(ang) * yr;
          ctx.beginPath(); ctx.arc(dx, dy, 2.5, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(180,240,255,${c.a + .3})`; ctx.fill();
        }
        ctx.restore();
      }
    }
    _sphere(ctx, t, s, rms, data) {
      const rotY = t * .3, tiltX = -.25;
      const sY = Math.sin(rotY), cY = Math.cos(rotY), sX = Math.sin(tiltX), cX = Math.cos(tiltX);
      const base = s === 'idle' ? .18 : s === 'listening' ? .45 : s === 'speaking' ? .75 : s === 'thinking' ? .5 : .3;
      const breath = s === 'speaking' ? rms * 7 : Math.sin(t * 2) * 1.5;
      const rad = R + breath;
      for (const p of DOTS) {
        const x1 = p.x * cY - p.z * sY, z1 = p.x * sY + p.z * cY;
        const y2 = p.y * cX - z1 * sX, z2 = p.y * sX + z1 * cX;
        const sx = CX + x1 * rad, sy = CY + y2 * rad;
        const depth = (z2 + 1) / 2;
        let a = base * (.2 + depth * .8);
        if (s === 'speaking' && data) a += (data[p.band % data.length] / 255) * .4 * depth;
        a = Math.min(1, a);
        const size = 1.3 + depth * .6 + (s === 'speaking' ? rms * .6 : 0);
        ctx.beginPath(); ctx.arc(sx, sy, size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(150,230,255,${a})`; ctx.fill();
      }
    }
    _eq(ctx, data, s) {
      const N = 32, bw = 4, gap = 2, total = N * (bw + gap) - gap, x0 = CX - total / 2, baseY = 350;
      const now = performance.now();
      for (let i = 0; i < N; i++) {
        let h, a = .4;
        if (s === 'speaking' && data) { h = (data[Math.floor(i / N * data.length)] / 255) * 40; a = .85; }
        else if (s === 'listening') h = 2 + Math.sin(now / 200 + i * .4) * 1.5;
        else if (s === 'thinking') h = 3 + Math.sin(now / 300 + i * .2) * 1.2;
        else h = 1.5;
        ctx.fillStyle = `rgba(0,220,255,${a})`;
        ctx.fillRect(x0 + i * (bw + gap), baseY - h, bw, Math.max(1, h));
      }
    }
  }

  window.Orb = Orb;
})();
