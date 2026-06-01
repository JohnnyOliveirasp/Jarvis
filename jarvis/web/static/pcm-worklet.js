// AudioWorklet: acumula audio do mic e posta blocos de 1280 amostras (80ms @16k)
// convertidos para PCM16 (Int16). Reduz overhead de WebSocket vs postar 128 amostras.
class PCMWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = [];
    this.target = 1280; // 80 ms @ 16 kHz
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) this.buf.push(ch[i]);
    while (this.buf.length >= this.target) {
      const slice = this.buf.splice(0, this.target);
      const i16 = new Int16Array(this.target);
      for (let j = 0; j < this.target; j++) {
        let s = Math.max(-1, Math.min(1, slice[j]));
        i16[j] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      this.port.postMessage(i16.buffer, [i16.buffer]);
    }
    return true;
  }
}
registerProcessor('pcm-worklet', PCMWorklet);
