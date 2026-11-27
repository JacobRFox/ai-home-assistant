// AudioWorklet: mic audio (usually 48 kHz float) -> 16 kHz mono Int16, posted in 80 ms
// chunks (1280 samples), the frame size openWakeWord expects.
const TARGET_RATE = 16000;
const CHUNK = 1280;

class Pcm16Downsampler extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE;
    this.pos = 0;            // fractional read position into the incoming stream
    this.acc = 0; this.n = 0; // running average for the current output sample
    this.out = new Int16Array(CHUNK);
    this.len = 0;
  }

  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    let peak = 0;
    for (let i = 0; i < input.length; i++) {
      // Box-filter average over each output sample's span: cheap anti-aliasing for speech.
      this.acc += input[i]; this.n++;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        const s = Math.max(-1, Math.min(1, this.acc / this.n));
        this.acc = 0; this.n = 0;
        peak = Math.max(peak, Math.abs(s));
        this.out[this.len++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this.len === CHUNK) {
          this.port.postMessage({ pcm: this.out.buffer, peak }, [this.out.buffer]);
          this.out = new Int16Array(CHUNK);
          this.len = 0; peak = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor('pcm16-downsampler', Pcm16Downsampler);
