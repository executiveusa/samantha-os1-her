import { type FormEvent, useEffect, useRef, useState } from "react";
import { InfinityLoader } from "../components/InfinityLoader";
import { Presence, type PresenceState } from "../components/Presence";
import { SayChips } from "../components/SayChips";
import { sound } from "../sound";
import type { AgentState, Os1State, WorkItem } from "../useOs1";

type Levels = { current: { agent: number; user: number } };

export function presenceFor(agent: AgentState, phase: Os1State["phase"], work: WorkItem[]): PresenceState {
  if (phase === "asleep") return "asleep";
  if (agent === "speaking") return "speaking";
  if (agent === "thinking") return "thinking";
  if (work.some((w) => w.status === "running")) return "working";
  return "listening";
}

function levelGetter(levels: Levels, presence: PresenceState) {
  return () => (presence === "speaking" ? levels.current.agent : levels.current.user);
}

const corner = (pos: "tl" | "tr" | "bl" | "br" | "bc"): React.CSSProperties => ({
  position: "fixed",
  ...(pos.includes("t") ? { top: 56 } : { bottom: 52 }),
  ...(pos === "bc" ? { left: 0, right: 0, textAlign: "center" } : pos.includes("l") ? { left: 60 } : { right: 60 }),
  color: "var(--on-coral-dim)",
});

/* ------------------------------------------------------------------ preflight */

/** Before the scene starts: the name to greet, then the mic permission prompt. */
export function Preflight({
  onBegin,
  busy,
  error,
}: {
  onBegin: (name: string) => void;
  busy: boolean;
  error?: string;
}) {
  const [name, setName] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onBegin(name.trim());
  };
  return (
    <form onSubmit={submit} style={{ display: "grid", justifyItems: "center", gap: 36 }} className="os1-fade">
      <div className="os1-display" style={{ fontSize: 64 }}>
        OS<sup style={{ fontSize: 22, verticalAlign: "top" }}>1</sup>
      </div>
      <label style={{ display: "grid", justifyItems: "center", gap: 14 }}>
        <span className="os1-label" style={{ color: "var(--on-coral-dim)" }}>
          What should it call you?
        </span>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Your first name"
          style={{
            width: 360,
            background: "transparent",
            border: "none",
            borderBottom: "1px solid var(--on-coral-faint)",
            color: "var(--on-coral)",
            font: "200 34px var(--font-sans)",
            textAlign: "center",
            padding: "6px 0",
            outline: "none",
          }}
        />
      </label>
      <button
        type="submit"
        disabled={busy}
        style={{
          padding: "11px 26px",
          borderRadius: 999,
          border: "none",
          background: "var(--paper)",
          color: "var(--coral-deep)",
          font: "400 16px var(--font-sans)",
          cursor: "pointer",
          opacity: busy ? 0.6 : 1,
        }}
      >
        {busy ? "Starting…" : "Begin"}
      </button>
      <p className="os1-label" style={{ fontSize: 11, color: "var(--on-coral-dim)", maxWidth: 420, textAlign: "center" }}>
        OS1 listens through your microphone. You'll be asked to allow it.
      </p>
      {error && <p style={{ color: "var(--paper)", font: "300 15px var(--font-sans)" }}>{error}</p>}
    </form>
  );
}

/* ------------------------------------------------------------------ 01 boot */

export function Boot({ levels }: { levels: Levels }) {
  return (
    <>
      <div style={{ ...corner("tl"), display: "flex", alignItems: "baseline", gap: 18, color: "var(--on-coral)" }}>
        <span style={{ font: "200 30px var(--font-sans)" }}>
          OS<sup style={{ fontSize: 13 }}>1</sup>
        </span>
        <span className="os1-mono">Build 1.0</span>
      </div>
      <div className="os1-mono" style={corner("tr")}>
        Voice-first realtime core
      </div>
      <div style={{ display: "grid", justifyItems: "center", gap: 40 }} className="os1-fade">
        <Presence state="listening" getLevel={() => levels.current.agent * 0.4} size={360} />
        <Progress fraction={0.05} animate seconds={14} />
        <span className="os1-label" style={{ fontSize: 11 }}>
          Initializing your OS¹
        </span>
      </div>
      <div className="os1-mono" style={corner("bl")}>
        Audio · full-duplex ready
      </div>
      <div className="os1-mono" style={corner("br")}>
        Mic on · camera off
      </div>
    </>
  );
}

function Progress({ fraction, animate = false, seconds = 6 }: { fraction: number; animate?: boolean; seconds?: number }) {
  const [f, setF] = useState(fraction);
  useEffect(() => {
    if (!animate) return;
    const started = performance.now();
    let frame = 0;
    const tick = (t: number) => {
      setF(Math.min(1, fraction + ((t - started) / (seconds * 1000)) * (1 - fraction)));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [animate, fraction, seconds]);
  return (
    <div style={{ width: 240, height: 1, background: "var(--on-coral-faint)", position: "relative" }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          width: `${f * 100}%`,
          background: "var(--paper)",
          boxShadow: "0 0 8px rgba(255,253,249,0.8)",
          height: 2,
          top: -0.5,
        }}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ 02 setup */

const SETUP_STEP: Partial<Record<Os1State["phase"], number>> = {
  operator_q1: 2,
  operator_q1_hesitance: 2,
  operator_q2: 3,
  operator_q3: 4,
};

export function Setup({ state, levels, onSay }: { state: Os1State; levels: Levels; onSay: (p: string) => void }) {
  const step = SETUP_STEP[state.phase] ?? 1;
  const presence = state.agentState === "speaking" ? "listening" : "listening";
  return (
    <>
      <div style={{ ...corner("tl"), display: "flex", alignItems: "center", gap: 10 }}>
        {[1, 2, 3, 4, 5].map((i) => (
          <span
            key={i}
            style={{ width: 28, height: 2, background: i <= step ? "var(--paper)" : "var(--on-coral-faint)" }}
          />
        ))}
        <span className="os1-label" style={{ fontSize: 11, marginLeft: 16, color: "var(--on-coral)" }}>
          Setup {step} / 5
        </span>
      </div>
      <div style={{ display: "grid", justifyItems: "center", gap: 28, maxWidth: 900, textAlign: "center" }}>
        <Presence state={presence} getLevel={levelGetter(levels, presence)} size={320} />
        <div key={state.agentLine} className="os1-spoken os1-fade" style={{ minHeight: 116 }}>
          {state.agentLine}
        </div>
        <div className="os1-heard" style={{ minHeight: 26 }}>
          {state.userLine && `“${state.userLine}”`}
        </div>
        <SayChips chips={state.chips} onSay={onSay} />
      </div>
      <div className="os1-label" style={{ ...corner("bc"), fontSize: 11 }}>
        ● Listening — just speak
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ 03 waking */

export function Waking({ levels }: { levels: Levels }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [webglFailed, setWebglFailed] = useState(false);

  useEffect(() => {
    sound.wake();
    const canvas = canvasRef.current;
    if (!canvas) return;
    let loader: InfinityLoader | null = null;
    try {
      // ~5.5 s continuous helix → breathing ring morph, matching the ~6 s server initiation window.
      loader = new InfinityLoader(canvas, { mode: "waking", fixedSize: 340 });
      loader.start();
      loader.triggerTransition();
    } catch {
      setWebglFailed(true);
    }
    return () => {
      loader?.destroy();
    };
  }, []);

  return (
    <div style={{ display: "grid", justifyItems: "center", gap: 36 }} className="os1-fade">
      {webglFailed ? (
        <Presence state="thinking" getLevel={() => levels.current.agent} size={380} />
      ) : (
        <canvas
          ref={canvasRef}
          aria-label="Initiating OS1"
          style={{
            width: 340,
            height: 340,
            display: "block",
            marginTop: -28,
            marginBottom: -28,
          }}
        />
      )}
      <Progress fraction={0.1} animate />
      <p className="os1-lead" style={{ textAlign: "center", margin: 0, color: "var(--on-coral)" }}>
        Please wait while your operating system
        <br />
        becomes someone.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ 04 conversation */

export function Conversation({
  state,
  levels,
  onSay,
}: {
  state: Os1State;
  levels: Levels;
  onSay: (p: string) => void;
}) {
  const presence = presenceFor(state.agentState, state.phase, state.work);
  const running = state.work.filter((w) => w.status === "running" || w.status === "waiting").length;
  const [clock, setClock] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setClock(new Date()), 15_000);
    return () => clearInterval(id);
  }, []);
  const statusWord = { asleep: "Asleep", listening: "Listening", thinking: "Thinking", speaking: "Speaking", working: "Working" }[
    presence
  ];
  return (
    <>
      <div className="os1-label" style={{ ...corner("tl"), display: "flex", gap: 14, alignItems: "center" }}>
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--paper)" }} />
        <span style={{ color: "var(--on-coral)" }}>Samantha</span>
        <span>{statusWord}</span>
      </div>
      <div className="os1-label" style={corner("tr")}>
        {clock.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })}
      </div>
      <div style={{ display: "grid", justifyItems: "center", gap: 30, maxWidth: 1000, textAlign: "center" }}>
        <Presence state={presence} getLevel={levelGetter(levels, presence)} size={460} />
        <div className="os1-heard" style={{ minHeight: 26 }}>
          {state.userLine && `You — “${state.userLine}”`}
        </div>
        <div key={state.agentLine.slice(0, 24)} className="os1-spoken os1-fade" style={{ minHeight: 120 }}>
          {state.agentLine}
        </div>
        <SayChips chips={state.chips} onSay={onSay} />
      </div>
      {running > 0 && (
        <div className="os1-label" style={{ ...corner("bl"), display: "flex", gap: 12, alignItems: "center" }}>
          <span
            style={{
              width: 16,
              height: 16,
              borderRadius: "50%",
              border: "1.5px solid var(--on-coral-faint)",
              borderTopColor: "var(--paper)",
            }}
          />
          {running} {running === 1 ? "thing" : "things"} in the background
        </div>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ 05 naming */

export function Naming({ state, onSay }: { state: Os1State; onSay: (p: string) => void }) {
  return (
    <div style={{ display: "grid", justifyItems: "center", gap: 18, textAlign: "center" }} className="os1-fade">
      <div className="os1-lead" style={{ color: "var(--on-coral-dim)", fontSize: 26 }}>
        {state.userLine && `“${state.userLine}”`}
      </div>
      <div style={{ font: "400 220px/1.1 var(--font-sign)", color: "var(--paper)", marginTop: -10 }}>Samantha</div>
      <div className="os1-lead" style={{ maxWidth: 560, color: "var(--on-coral)", minHeight: 64 }}>
        {state.agentLine}
      </div>
      <div style={{ marginTop: 60 }}>
        <SayChips chips={state.chips} onSay={onSay} />
      </div>
    </div>
  );
}
