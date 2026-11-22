/**
 * OS1 sound design — every sound is synthesized live with WebAudio (no audio files,
 * nothing to license). Warm just-intonation harmonics in D, a generated room reverb,
 * and quiet UI cues that stay under her voice.
 *
 *   boot()       ~9.5 s  startup: pad breath → harmonic bloom → glass shimmer → resolve
 *   wake()       ~7 s    initiation (Paper 03): bell strikes rising into a full chord
 *   listen()             session connected / she's listening
 *   workStart()  workDone()   background task started / finished
 *   tap()  sleep()  wakeUp()  disconnect()
 *
 * Works with a live AudioContext or an OfflineAudioContext (for rendering previews).
 */

type Ctx = BaseAudioContext;

const D2 = 73.42;
// Just-intonation ratios over D: unison, fifth, octave, major third, etc.
const hz = (ratio: number, octave = 0) => D2 * ratio * 2 ** octave;

const MUTE_KEY = "os1.sound.muted";

export class Os1Sound {
  private ctx: Ctx | null = null;
  private out: GainNode | null = null;
  private wet: GainNode | null = null;
  private dry: GainNode | null = null;
  private muteListeners = new Set<(muted: boolean) => void>();

  constructor(ctx?: Ctx) {
    if (ctx) this.attach(ctx);
  }

  get muted(): boolean {
    try {
      return localStorage.getItem(MUTE_KEY) === "1";
    } catch {
      return false;
    }
  }

  set muted(value: boolean) {
    try {
      localStorage.setItem(MUTE_KEY, value ? "1" : "0");
    } catch {
      /* per-viewer convenience only */
    }
    if (this.out) this.out.gain.value = value ? 0 : 0.9;
    this.muteListeners.forEach((fn) => fn(value));
  }

  onMuteChange(fn: (muted: boolean) => void): () => void {
    this.muteListeners.add(fn);
    return () => this.muteListeners.delete(fn);
  }

  private attach(ctx: Ctx): void {
    this.ctx = ctx;
    const out = ctx.createGain();
    out.gain.value = typeof localStorage !== "undefined" && this.muted ? 0 : 0.9;
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -14;
    comp.ratio.value = 3;
    out.connect(comp).connect(ctx.destination);
    const reverb = ctx.createConvolver();
    reverb.buffer = roomImpulse(ctx, 3.4, 2.6);
    this.wet = ctx.createGain();
    this.wet.gain.value = 0.42;
    this.dry = ctx.createGain();
    this.dry.gain.value = 0.8;
    this.wet.connect(reverb).connect(out);
    this.dry.connect(out);
    this.out = out;
  }

  /** Lazily create the live context (must follow a user gesture in browsers; Electron allows autoplay). */
  private live(): Ctx | null {
    if (!this.ctx) {
      try {
        this.attach(new AudioContext());
      } catch {
        return null;
      }
    }
    const ctx = this.ctx as AudioContext;
    if ("resume" in ctx && ctx.state === "suspended") void ctx.resume();
    return ctx;
  }

  // ------------------------------------------------------------------ voices

  /** Slow, breathing tone: sine with a little vibrato. */
  private pad(f: number, start: number, attack: number, hold: number, release: number, level: number, pan = 0): void {
    const ctx = this.ctx!;
    const osc = ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = f;
    const vib = ctx.createOscillator();
    vib.frequency.value = 4.2 + Math.random() * 0.8;
    const vibGain = ctx.createGain();
    vibGain.gain.value = f * 0.0025;
    vib.connect(vibGain).connect(osc.frequency);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, start);
    g.gain.linearRampToValueAtTime(level, start + attack);
    g.gain.setValueAtTime(level, start + attack + hold);
    g.gain.exponentialRampToValueAtTime(0.0001, start + attack + hold + release);
    const p = ctx.createStereoPanner();
    p.pan.value = pan;
    osc.connect(g).connect(p);
    p.connect(this.dry!);
    p.connect(this.wet!);
    const end = start + attack + hold + release + 0.1;
    osc.start(start);
    vib.start(start);
    osc.stop(end);
    vib.stop(end);
  }

  /** Warm low bed: detuned saws through a slowly opening low-pass. */
  private bed(f: number, start: number, dur: number, level: number): void {
    const ctx = this.ctx!;
    const lp = ctx.createBiquadFilter();
    lp.type = "lowpass";
    lp.Q.value = 0.7;
    lp.frequency.setValueAtTime(160, start);
    lp.frequency.exponentialRampToValueAtTime(1500, start + dur * 0.6);
    lp.frequency.exponentialRampToValueAtTime(380, start + dur);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, start);
    g.gain.linearRampToValueAtTime(level, start + dur * 0.45);
    g.gain.exponentialRampToValueAtTime(0.0001, start + dur);
    lp.connect(g);
    g.connect(this.dry!);
    g.connect(this.wet!);
    for (const detune of [-7, 0, 6]) {
      const osc = ctx.createOscillator();
      osc.type = "sawtooth";
      osc.frequency.value = f;
      osc.detune.value = detune;
      osc.connect(lp);
      osc.start(start);
      osc.stop(start + dur + 0.1);
    }
  }

  /** Glass/bell strike: two-operator FM with a quick attack and long decay. */
  private bell(f: number, start: number, decay: number, level: number, pan = 0): void {
    const ctx = this.ctx!;
    const car = ctx.createOscillator();
    car.frequency.value = f;
    const mod = ctx.createOscillator();
    mod.frequency.value = f * 3.5;
    const modGain = ctx.createGain();
    modGain.gain.setValueAtTime(f * 1.2, start);
    modGain.gain.exponentialRampToValueAtTime(f * 0.02, start + decay * 0.6);
    mod.connect(modGain).connect(car.frequency);
    const g = ctx.createGain();
    g.gain.setValueAtTime(0, start);
    g.gain.linearRampToValueAtTime(level, start + 0.012);
    g.gain.exponentialRampToValueAtTime(0.0001, start + decay);
    const p = ctx.createStereoPanner();
    p.pan.value = pan;
    car.connect(g).connect(p);
    p.connect(this.dry!);
    p.connect(this.wet!);
    car.start(start);
    mod.start(start);
    car.stop(start + decay + 0.1);
    mod.stop(start + decay + 0.1);
  }

  // ------------------------------------------------------------------ pieces

  /** Startup (~9.5 s). Timed with StartupSequence: breath 0–3 s, bloom 3–6 s, resolve ~6.2 s. */
  boot(at?: number): number {
    const ctx = this.ctx ?? this.live();
    if (!ctx) return 0;
    const t = at ?? ctx.currentTime + 0.05;
    // breath: low bed opening
    this.bed(D2, t + 0.3, 8.6, 0.05);
    this.bed(hz(3 / 2), t + 0.8, 8.0, 0.032);
    // harmonic bloom, partials entering one by one
    const bloom: [number, number, number][] = [
      [hz(1, 1), 1.4, -0.2],
      [hz(3 / 2, 1), 2.1, 0.2],
      [hz(1, 2), 2.8, -0.35],
      [hz(5 / 4, 2), 3.4, 0.35],
      [hz(3 / 2, 2), 3.9, -0.1],
      [hz(1, 3), 4.5, 0.1],
    ];
    for (const [f, enter, pan] of bloom) this.pad(f, t + enter, 1.8, 6.2 - enter, 3.2, 0.05, pan);
    // glass shimmer, then the resolving strike
    const shimmer: [number, number][] = [
      [hz(1, 4), 4.7],
      [hz(3 / 2, 4), 5.05],
      [hz(5 / 4, 4), 5.4],
      [hz(1, 5), 5.75],
    ];
    shimmer.forEach(([f, when], i) => this.bell(f, t + when, 2.6, 0.035, i % 2 ? 0.4 : -0.4));
    this.bell(hz(1, 3), t + 6.2, 4.2, 0.07, 0);
    this.bell(hz(3 / 2, 3), t + 6.22, 4.0, 0.045, 0.25);
    this.pad(hz(5 / 4, 3), t + 6.1, 0.4, 0.6, 3.0, 0.03, -0.25);
    return 9.6;
  }

  /** Initiation (~6 s): warm harmonic swell she wakes into, no bell arpeggio. */
  wake(at?: number): number {
    const ctx = this.ctx ?? this.live();
    if (!ctx) return 0;
    const t = at ?? ctx.currentTime + 0.05;
    this.bed(D2, t + 0.1, 5.8, 0.045);
    this.bed(hz(3 / 2), t + 0.4, 5.4, 0.03);
    for (const [r, o, enter, pan] of [
      [1, 1, 0.4, -0.25],
      [3 / 2, 1, 1.0, 0.25],
      [1, 2, 1.6, -0.18],
      [5 / 4, 2, 2.2, 0.18],
      [3 / 2, 2, 2.8, 0],
    ] as const) {
      this.pad(hz(r, o), t + enter, 1.6, Math.max(0.4, 4.4 - enter), 2.2, 0.042, pan);
    }
    return 6.6;
  }

  listen(): void {
    if (!this.live()) return;
    const t = this.ctx!.currentTime + 0.02;
    this.bell(hz(3 / 2, 3), t, 0.9, 0.03, -0.1);
    this.bell(hz(1, 4), t + 0.14, 1.2, 0.03, 0.1);
  }

  workStart(): void {
    if (!this.live()) return;
    this.bell(hz(1, 4), this.ctx!.currentTime + 0.02, 0.8, 0.022, 0.3);
  }

  workDone(): void {
    if (!this.live()) return;
    const t = this.ctx!.currentTime + 0.02;
    this.bell(hz(3 / 2, 4), t, 1.4, 0.028, 0.2);
    this.bell(hz(1, 5), t + 0.16, 1.8, 0.028, 0.3);
  }

  tap(): void {
    if (!this.live()) return;
    this.bell(hz(5 / 4, 5), this.ctx!.currentTime + 0.005, 0.25, 0.014, 0);
  }

  sleep(): void {
    if (!this.live()) return;
    const t = this.ctx!.currentTime + 0.02;
    [hz(1, 4), hz(3 / 2, 3), hz(1, 3)].forEach((f, i) => this.pad(f, t + i * 0.32, 0.15, 0.15, 1.6, 0.03));
  }

  wakeUp(): void {
    if (!this.live()) return;
    const t = this.ctx!.currentTime + 0.02;
    [hz(1, 3), hz(3 / 2, 3), hz(1, 4)].forEach((f, i) => this.bell(f, t + i * 0.12, 1.2, 0.028));
  }

  disconnect(): void {
    if (!this.live()) return;
    this.pad(hz(1, 2), this.ctx!.currentTime + 0.02, 0.1, 0.2, 1.4, 0.03);
  }
}

/** Generated stereo room: decaying noise, a little darker at the tail. */
function roomImpulse(ctx: Ctx, seconds: number, decay: number): AudioBuffer {
  const len = Math.floor(ctx.sampleRate * seconds);
  const buf = ctx.createBuffer(2, len, ctx.sampleRate);
  for (let ch = 0; ch < 2; ch++) {
    const data = buf.getChannelData(ch);
    let lp = 0;
    for (let i = 0; i < len; i++) {
      const x = i / len;
      lp = lp * 0.6 + (Math.random() * 2 - 1) * 0.4; // gentle low-pass on the noise
      data[i] = lp * (1 - x) ** decay;
    }
  }
  return buf;
}

export const sound = new Os1Sound();
