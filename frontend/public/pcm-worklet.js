// Converts mic audio (any sample rate, Float32) into 16 kHz mono PCM16 chunks
// of ~100 ms and posts them to the main thread along with an RMS level.
class PcmWorklet extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetRate = options.processorOptions?.targetRate || 16000;
    this.ratio = sampleRate / this.targetRate; // e.g. 48000/16000 = 3
    this.chunkSize = Math.round(this.targetRate / 10); // 100 ms
    this.buf = new Int16Array(this.chunkSize);
    this.len = 0;
    this.acc = 0; // running sum for box-filter downsampling
    this.cnt = 0;
    this.pos = 0;
    this.sumSq = 0;
  }

  push(s) {
    s = Math.max(-1, Math.min(1, s));
    this.sumSq += s * s;
    this.buf[this.len++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    if (this.len === this.chunkSize) {
      const rms = Math.sqrt(this.sumSq / this.chunkSize);
      this.port.postMessage({ pcm: this.buf.buffer, rms }, [this.buf.buffer]);
      this.buf = new Int16Array(this.chunkSize);
      this.len = 0;
      this.sumSq = 0;
    }
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    if (this.ratio <= 1) {
      for (let i = 0; i < ch.length; i++) this.push(ch[i]);
      return true;
    }
    for (let i = 0; i < ch.length; i++) {
      this.acc += ch[i];
      this.cnt++;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        this.push(this.acc / this.cnt);
        this.acc = 0;
        this.cnt = 0;
      }
    }
    return true;
  }
}

registerProcessor("pcm-worklet", PcmWorklet);
