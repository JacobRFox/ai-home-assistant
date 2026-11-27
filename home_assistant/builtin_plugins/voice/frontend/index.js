import { PluginElement, esc, postToChat } from '/static/sdk.js';

const STATES = {
  off: 'Microphone off',
  loading: 'Loading speech models…',
  idle: 'Listening for the wake word',
  recording: 'Listening…',
  thinking: 'Thinking…',
  speaking: 'Speaking…',
};
const pref = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem(`voice.${k}`)) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(`voice.${k}`, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

class Voice extends PluginElement {
  async init() {
    this.state = 'off';
    this.speak = pref.get('speak', true);
    this.wakePhrase = 'the wake word';
    this.innerHTML = `
      <div class="stack">
        <div class="row">
          <button class="btn" data-action="toggle" style="min-width: 150px">🎤 Start listening</button>
          <button class="btn btn-ghost" data-action="talk" hidden>Talk now</button>
        </div>
        <div class="row small">
          <span data-dot style="width: 8px; height: 8px; border-radius: 50%; background: var(--muted); flex: none"></span>
          <span class="grow" data-status>${STATES.off}</span>
        </div>
        <div style="height: 4px; border-radius: 2px; background: var(--surface-2); overflow: hidden">
          <div data-level style="height: 100%; width: 0; background: var(--accent); transition: width 80ms linear"></div>
        </div>
        <p class="muted small" data-hint></p>
        <label class="row small"><input type="checkbox" data-action="speak" ${this.speak ? 'checked' : ''}> Read replies aloud</label>
      </div>`;
    this.addEventListener('click', (e) => {
      const action = e.target.closest('[data-action]')?.dataset.action;
      if (action === 'toggle') this.state === 'off' ? this.start() : this.stop();
      if (action === 'talk') this.send({ type: 'talk' });
    });
    this.querySelector('[data-action="speak"]').addEventListener('change', (e) => pref.set('speak', (this.speak = e.target.checked)));
    const status = await this.api.get('/status');
    this.applyStatus(status);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.stop();
  }

  applyStatus(s) {
    this.wakePhrase = `“${s.wake_phrase}”`;
    this.querySelector('[data-hint]').innerHTML = s.error
      ? `<span class="error">${esc(s.error)}</span>`
      : `Say ${esc(this.wakePhrase)}, then your request. Audio is processed on this computer.`;
    this.querySelector('[data-action="toggle"]').disabled = Boolean(s.error);
    if (s.error && this.state !== 'off') this.stop();
    if (this.state === 'loading' && s.ready) this.setState('idle');
  }

  setState(state, detail) {
    this.state = state;
    const text = state === 'idle' ? `Listening for ${this.wakePhrase}` : STATES[state];
    this.querySelector('[data-status]').textContent = detail ? `${text} ${detail}` : text;
    const live = state !== 'off';
    this.querySelector('[data-dot]').style.background =
      state === 'recording' ? 'var(--danger)' : live && state !== 'loading' ? 'var(--ok)' : 'var(--muted)';
    this.querySelector('[data-action="toggle"]').textContent = live ? '■ Stop listening' : '🎤 Start listening';
    this.querySelector('[data-action="talk"]').hidden = state !== 'idle';
    if (!live) this.querySelector('[data-level]').style.width = '0';
  }

  send(msg) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(typeof msg === 'string' || msg instanceof ArrayBuffer ? msg : JSON.stringify(msg));
  }

  async start() {
    try {
      this.media = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      this.notify(`Microphone unavailable: ${e.message}`, true);
      return;
    }
    this.setState('loading');
    this.audio = new AudioContext();
    await this.audio.audioWorklet.addModule(`/plugins/${this.pluginId}/worklet.js`);
    const source = this.audio.createMediaStreamSource(this.media);
    this.worklet = new AudioWorkletNode(this.audio, 'pcm16-downsampler');
    this.worklet.port.onmessage = ({ data }) => {
      this.querySelector('[data-level]').style.width = `${Math.min(100, data.peak * 140)}%`;
      if (this.state !== 'speaking' && this.state !== 'thinking') this.send(data.pcm);
    };
    source.connect(this.worklet);

    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    this.ws = new WebSocket(`${proto}://${location.host}/api/plugins/${this.pluginId}/stream`);
    this.ws.binaryType = 'arraybuffer';
    this.ws.onmessage = (e) => this.onServer(JSON.parse(e.data));
    this.ws.onclose = () => { if (this.state !== 'off') { this.notify('Voice connection closed.', true); this.stop(); } };
  }

  stop() {
    this.ws?.close(); this.ws = null;
    this.media?.getTracks().forEach((t) => t.stop()); this.media = null;
    this.audio?.close(); this.audio = null;
    speechSynthesis.cancel();
    if (this.isConnected) this.setState('off');
  }

  onServer(msg) {
    switch (msg.type) {
      case 'status':
        this.applyStatus(msg);
        if (msg.ready && this.state === 'loading') this.setState('idle');
        break;
      case 'wake':
        this.chime();
        this.setState('recording');
        break;
      case 'processing':
        this.setState('thinking');
        postToChat('assistant', 'Thinking…', { pending: true });
        break;
      case 'transcript':
        postToChat('user', `🎤 ${msg.text}`);
        postToChat('assistant', 'Thinking…', { pending: true });
        break;
      case 'reply':
        postToChat('assistant', msg.text, { steps: msg.steps });
        this.say(msg.text);
        break;
      case 'nothing_heard':
        postToChat('assistant', '(didn’t catch that)');
        this.setState('idle');
        break;
      case 'error':
        postToChat('error', msg.message);
        this.setState('idle');
        break;
      case 'listening':
        if (this.state !== 'speaking') this.setState('idle');
        break;
    }
  }

  say(text) {
    if (!this.speak || !('speechSynthesis' in window)) { this.setState('idle'); return; }
    // Don't stream the mic while talking, or the assistant could hear (and wake) itself.
    this.setState('speaking');
    const u = new SpeechSynthesisUtterance(text.replace(/\[fake model\]\s*/g, ''));
    u.onend = u.onerror = () => {
      if (this.state !== 'speaking') return;
      this.send({ type: 'resume' });
      this.setState('idle');
    };
    speechSynthesis.speak(u);
  }

  chime() {
    if (!this.audio) return;
    const t = this.audio.currentTime, osc = this.audio.createOscillator(), gain = this.audio.createGain();
    osc.frequency.setValueAtTime(880, t); osc.frequency.setValueAtTime(1320, t + 0.09);
    gain.gain.setValueAtTime(0.0001, t); gain.gain.exponentialRampToValueAtTime(0.15, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
    osc.connect(gain).connect(this.audio.destination);
    osc.start(t); osc.stop(t + 0.26);
  }
}

customElements.define('plugin-voice', Voice);
