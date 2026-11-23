import { App, type Os1Config } from "@os1/ui";
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

declare global {
  interface Window {
    os1?: {
      config?: Os1Config;
      getConfig?: () => Promise<Os1Config>;
    };
  }
}

function resolveWebConfig(): Os1Config {
  const isHosted = (window.location.protocol === "http:" || window.location.protocol === "https:") && window.location.port !== "5173";
  // Never ingest a privileged service token from URL fragments or localStorage.
  try { window.localStorage.removeItem("os1_client_token"); } catch { /* optional cleanup */ }
  return { orchestratorUrl: isHosted ? window.location.origin : "http://127.0.0.1:8787" };
}

const FALLBACK_CONFIG: Os1Config = resolveWebConfig();

if ("serviceWorker" in navigator && (window.location.protocol === "https:" || window.location.hostname === "localhost")) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("./sw.js").catch(() => undefined);
  });
}

type AuthState = "checking" | "signed-out" | "signed-in" | "unconfigured";
const panel: React.CSSProperties = {
  boxSizing: "border-box", width: "min(420px, calc(100vw - 32px))", padding: 32,
  color: "#fafafa", background: "#15161c", border: "1px solid #34363d",
  borderRadius: 20, fontFamily: "Inter, system-ui, sans-serif",
};
const field: React.CSSProperties = {
  width: "100%", boxSizing: "border-box", padding: 13, marginTop: 12,
  border: "1px solid #484b56", borderRadius: 9, background: "#202129",
  color: "#fff", fontSize: 16,
};

function SignIn({ onAuthenticated }: { onAuthenticated: () => void }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try {
      const response = await fetch("/os1/auth/login", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({})) as { detail?: string };
        throw new Error(body.detail || "Sign-in failed");
      }
      setPassword("");
      onAuthenticated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally { setBusy(false); }
  }
  return (
    <main style={{ minHeight: "100dvh", display: "grid", placeItems: "center", background: "#0c0d11" }}>
      <form onSubmit={(e) => { void submit(e); }} style={panel}>
        <h1 style={{ margin: "0 0 10px", fontSize: 26, fontWeight: 600 }}>Synthia</h1>
        <p style={{ color: "#b8bac5", lineHeight: 1.5, margin: 0 }}>
          Sign in to begin your private session.
        </p>
        <label htmlFor="synthia-passphrase" style={{ display: "block", marginTop: 24, fontSize: 14 }}>
          Preview passphrase
        </label>
        <input id="synthia-passphrase" type="password" autoComplete="current-password"
          required value={password} onChange={(e) => setPassword(e.target.value)}
          style={field} />
        {error && <p role="alert" style={{ color: "#ff9999", fontSize: 13 }}>{error}</p>}
        <button disabled={busy} type="submit" style={{
          ...field, background: "#e5e5ea", color: "#15151a", cursor: busy ? "wait" : "pointer",
          fontWeight: 650, marginTop: 20,
        }}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}

function Root() {
  const [config, setConfig] = useState<Os1Config | null>(() =>
    window.os1?.config ?? (window.os1?.getConfig ? null : FALLBACK_CONFIG));
  const hostedWeb = !window.os1 && window.location.protocol === "https:";
  const [auth, setAuth] = useState<AuthState>(hostedWeb ? "checking" : "signed-in");

  useEffect(() => {
    if (config || !window.os1?.getConfig) return;
    let alive = true;
    void window.os1.getConfig()
      .then((c) => { if (alive) setConfig(c); })
      .catch(() => { if (alive) setConfig(FALLBACK_CONFIG); });
    return () => { alive = false; };
  }, [config]);

  useEffect(() => {
    if (!hostedWeb) return;
    let alive = true;
    void fetch("/os1/auth/session", { credentials: "same-origin", cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Sign-in status unavailable");
        return response.json() as Promise<{ authenticated: boolean; configured: boolean }>;
      })
      .then((session) => {
        if (alive) setAuth(session.authenticated ? "signed-in" : session.configured ? "signed-out" : "unconfigured");
      })
      .catch(() => { if (alive) setAuth("unconfigured"); });
    return () => { alive = false; };
  }, [hostedWeb]);

  if (!config || auth === "checking") {
    return <main style={{ minHeight: "100dvh", display: "grid", placeItems: "center" }}>Loading Synthia…</main>;
  }
  if (auth === "unconfigured") {
    return <main style={{ minHeight: "100dvh", display: "grid", placeItems: "center", background: "#0c0d11" }}>
      <section style={panel}><h1>Synthia</h1><p>Preview sign-in is not configured or temporarily unavailable.</p></section>
    </main>;
  }
  if (auth === "signed-out") return <SignIn onAuthenticated={() => setAuth("signed-in")} />;
  return <App config={config} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode><Root /></StrictMode>,
);
