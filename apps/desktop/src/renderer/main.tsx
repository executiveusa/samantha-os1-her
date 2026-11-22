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
  const isHttp = window.location.protocol === "http:" || window.location.protocol === "https:";
  const orchestratorUrl =
    isHttp && window.location.port !== "5173" ? window.location.origin : "http://127.0.0.1:8787";

  let clientToken = "";
  try {
    const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const fromHash = hashParams.get("token");
    if (fromHash) {
      window.localStorage.setItem("os1_client_token", fromHash);
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
      clientToken = fromHash;
    } else {
      clientToken = window.localStorage.getItem("os1_client_token") ?? "";
    }
  } catch {
    /* private mode or non-browser context */
  }
  return clientToken ? { orchestratorUrl, clientToken } : { orchestratorUrl };
}

const FALLBACK_CONFIG: Os1Config = resolveWebConfig();

if ("serviceWorker" in navigator && (window.location.protocol === "https:" || window.location.hostname === "localhost")) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("./sw.js").catch(() => undefined);
  });
}

function Root() {
  const [config, setConfig] = useState<Os1Config | null>(() => window.os1?.config ?? (window.os1?.getConfig ? null : FALLBACK_CONFIG));

  useEffect(() => {
    if (config || !window.os1?.getConfig) return;
    let alive = true;
    void window.os1
      .getConfig()
      .then((c) => {
        if (alive) setConfig(c);
      })
      .catch(() => {
        if (alive) setConfig(FALLBACK_CONFIG);
      });
    return () => {
      alive = false;
    };
  }, [config]);

  if (!config) return null;
  return <App config={config} />;
}

// biome-ignore lint/style/noNonNullAssertion: root exists in index.html
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
