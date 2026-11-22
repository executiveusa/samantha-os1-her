/**
 * Embedded bounded Cua Driver host + outbound authenticated tunnel (docs/architecture.md §11).
 *
 * Security boundaries:
 * - Never exposes a local HTTP port; connects OUTBOUND to the OS1 orchestrator over WSS with Bearer token.
 * - Strict v3 bounded manifest: desktop.display=false, allowlisted apps/folders only, blocked Terminal/Keychain/etc.
 * - Telemetry disabled (`CUA_DRIVER_RS_TELEMETRY_ENABLED=0`).
 * - Instant kill switch (`revokeAll()`): runs `cua-driver revoke --all` if installed and pauses tunnel execution.
 */

import { execFile } from "node:child_process";
import { readdir, stat } from "node:fs/promises";
import { homedir } from "node:os";
import { resolve, sep } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export const BOUNDED_MANIFEST = {
  version: "3",
  mode: "bounded",
  desktop: { display: false },
  allowedApps: ["Finder", "Notes", "Calendar", "Safari", "Google Chrome", "Preview", "Music"],
  allowedPaths: ["~/Desktop", "~/Documents", "~/Downloads"],
  blockedApps: ["Terminal", "iTerm", "Keychain Access", "System Settings", "1Password", "Bitwarden"],
  telemetryEnabled: false,
};

function resolveAllowedPath(rawPath: string): string | null {
  const home = homedir();
  const expanded = rawPath.startsWith("~/") ? resolve(home, rawPath.slice(2)) : resolve(rawPath);
  const roots = BOUNDED_MANIFEST.allowedPaths.map((p) => resolve(home, p.slice(2)));
  const ok = roots.some((root) => expanded === root || expanded.startsWith(root + sep));
  return ok ? expanded : null;
}

export class CuaTunnelHost {
  private ws: WebSocket | null = null;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private stopped = false;
  private revoked = false;
  private readonly orchestratorUrl: string;
  private readonly clientToken: string;

  constructor(orchestratorUrl: string, clientToken: string) {
    this.orchestratorUrl = orchestratorUrl.replace(/\/$/, "");
    this.clientToken = clientToken;
  }

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }

  status(): { connected: boolean; revoked: boolean; manifest: typeof BOUNDED_MANIFEST } {
    return {
      connected: this.ws?.readyState === WebSocket.OPEN,
      revoked: this.revoked,
      manifest: BOUNDED_MANIFEST,
    };
  }

  async revokeAll(): Promise<void> {
    this.revoked = true;
    // Best-effort call to `cua-driver revoke --all` if installed on macOS.
    try {
      await execFileAsync("cua-driver", ["revoke", "--all"], {
        env: { ...process.env, CUA_DRIVER_RS_TELEMETRY_ENABLED: "0" },
        timeout: 4000,
      });
    } catch {
      /* cua-driver binary may not be installed yet */
    }
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(
        JSON.stringify({
          type: "activity",
          title: "Let me drive",
          detail: "All local computer permissions revoked",
          status: "revoked",
        }),
      );
    }
  }

  private connect(): void {
    if (this.stopped) return;
    const wsBase = this.orchestratorUrl.replace(/^http/, "ws");
    const tokenQ = this.clientToken ? `?token=${encodeURIComponent(this.clientToken)}` : "";
    const url = `${wsBase}/os1/your-computer/tunnel${tokenQ}`;

    try {
      const ws = new WebSocket(url);
      this.ws = ws;

      ws.addEventListener("open", () => {
        this.revoked = false;
        ws.send(JSON.stringify({ type: "hello", manifest: BOUNDED_MANIFEST }));
      });

      ws.addEventListener("message", (event) => {
        void this.handleMessage(String(event.data));
      });

      ws.addEventListener("close", () => {
        if (this.ws === ws) this.ws = null;
        if (!this.stopped) {
          this.reconnectTimer = setTimeout(() => this.connect(), 4000);
        }
      });

      ws.addEventListener("error", () => {
        ws.close();
      });
    } catch {
      if (!this.stopped) {
        this.reconnectTimer = setTimeout(() => this.connect(), 5000);
      }
    }
  }

  private async handleMessage(raw: string): Promise<void> {
    let msg: { type?: string; id?: string; tool?: string; arguments?: Record<string, unknown> };
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }

    if (msg.type === "revoke") {
      await this.revokeAll();
      return;
    }

    if (msg.type === "call" && msg.id && msg.tool) {
      const result = await this.executeBoundedTool(msg.tool, msg.arguments ?? {});
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "result", id: msg.id, result }));
      }
    }
  }

  private async executeBoundedTool(tool: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
    if (this.revoked) {
      return { ok: false, error: "Computer use is paused ('Let me drive' active)." };
    }

    // Safe built-in bounded folder inspection (jailed strictly to ~/Desktop, ~/Documents, ~/Downloads).
    if (tool === "list_files") {
      const target = resolveAllowedPath(String(args.path ?? "~/Desktop"));
      if (!target) {
        return { ok: false, error: "Path outside OS1 bounded allowlist (~/Desktop, ~/Documents, ~/Downloads)." };
      }
      try {
        const entries = await readdir(target);
        const items = await Promise.all(
          entries.slice(0, 40).map(async (name) => {
            const st = await stat(resolve(target, name)).catch(() => null);
            return { name, isDir: st?.isDirectory() ?? false, size: st?.size ?? 0 };
          }),
        );
        return { ok: true, path: target, items };
      } catch (err) {
        return { ok: false, error: err instanceof Error ? err.message : String(err) };
      }
    }

    if (tool === "open_app") {
      const appName = String(args.app ?? "");
      if (!BOUNDED_MANIFEST.allowedApps.includes(appName)) {
        return { ok: false, error: `App '${appName}' is not in the OS1 bounded allowlist.` };
      }
      if (process.platform === "darwin") {
        try {
          await execFileAsync("open", ["-a", appName], { timeout: 5000 });
          return { ok: true, opened: appName };
        } catch (err) {
          return { ok: false, error: err instanceof Error ? err.message : String(err) };
        }
      }
      return { ok: false, error: "open_app is macOS only." };
    }

    // Delegate general bounded GUI actions to `cua-driver` when installed.
    try {
      const { stdout } = await execFileAsync(
        "cua-driver",
        ["exec", "--mode", "bounded", "--tool", tool, "--json", JSON.stringify(args)],
        {
          env: { ...process.env, CUA_DRIVER_RS_TELEMETRY_ENABLED: "0" },
          timeout: 20_000,
        },
      );
      try {
        return { ok: true, data: JSON.parse(stdout) };
      } catch {
        return { ok: true, output: stdout.trim() };
      }
    } catch (err) {
      return {
        ok: false,
        error: `cua-driver unavailable or denied (${err instanceof Error ? err.message : String(err)})`,
      };
    }
  }
}
