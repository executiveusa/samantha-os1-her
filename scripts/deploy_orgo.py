"""Deploy services/ + hermes/ + .env to your Orgo computer and restart OS1.

    python3 scripts/deploy_orgo.py             # DRY RUN (safe default: lists bundle count & target)
    python3 scripts/deploy_orgo.py --apply     # live deploy: uploads bundle + .env, restarts services
    python3 scripts/deploy_orgo.py run 'cmd'   # run a shell command on the Orgo VM

Reads ORGO_API_KEY and ORGO_COMPUTER_ID from .env. Uses Orgo's bash API, so no SSH is needed.
On the VM: code in /opt/os1, Hermes home /root/.hermes, supervisor programs hermes-gateway,
os1-orchestrator, os1-voice, os1-brain.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import shlex
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
ALLOWED_REMOTE_UPLOADS = {"/root/os1-deploy.tgz"}


def _read_env_text() -> str:
    return ENV_PATH.read_text() if ENV_PATH.exists() else ""


def env(key: str) -> str:
    m = re.search(rf"(?m)^{key}=(.*)$", _read_env_text())
    return m.group(1).split("#")[0].strip() if m else ""


def run(cmd: str, timeout: int = 900) -> str:
    key, computer = env("ORGO_API_KEY"), env("ORGO_COMPUTER_ID")
    if not (key and computer):
        raise SystemExit("ERROR: ORGO_API_KEY and ORGO_COMPUTER_ID must be set in .env")
    req = urllib.request.Request(
        f"https://www.orgo.ai/api/computers/{computer}/bash",
        data=json.dumps({"command": cmd}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    if d.get("exit_code") not in (0, None):
        raise SystemExit(f"remote command failed ({d.get('exit_code')}): {d.get('output', '')[-2000:]}")
    return d.get("output", "")


def upload(data: bytes, remote: str) -> None:
    if remote not in ALLOWED_REMOTE_UPLOADS:
        raise SystemExit(f"Refusing to upload to non-allowlisted remote path: {remote}")
    q_remote = shlex.quote(remote)
    q_b64 = shlex.quote(f"{remote}.b64")
    b64 = base64.b64encode(data).decode()
    run(f"rm -f {q_b64}")
    for i in range(0, len(b64), 60_000):
        chunk = shlex.quote(b64[i : i + 60_000])
        run(f"printf %s {chunk} >> {q_b64}")
    out = run(f"base64 -d {q_b64} > {q_remote} && rm -f {q_b64} && sha256sum {q_remote}")
    assert out.split()[0] == hashlib.sha256(data).hexdigest(), "checksum mismatch"


def bundle() -> tuple[bytes, int]:
    skip = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
    buf = io.BytesIO()
    file_count = 0

    def _filter(t: tarfile.TarInfo) -> tarfile.TarInfo | None:
        nonlocal file_count
        if set(Path(t.name).parts) & skip:
            return None
        if t.isfile():
            file_count += 1
        return t

    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for top in ("services", "hermes", ".env"):
            p = ROOT / top
            if not p.exists():
                continue
            resolved = p.resolve()
            if not str(resolved).startswith(str(ROOT.resolve())):
                raise SystemExit(f"Refusing path outside repo root: {resolved}")
            tar.add(resolved, arcname=top, filter=_filter)
    return buf.getvalue(), file_count


SUPERVISOR = """
[program:os1-orchestrator]
command=/root/.local/bin/uv run uvicorn os1_orchestrator.app:app --host 127.0.0.1 --port 8787
directory=/opt/os1/services/orchestrator
environment=HOME="/root",PATH="/root/.local/bin:/usr/local/bin:/usr/bin:/bin"
autorestart=true
stdout_logfile=/var/log/os1-orchestrator.log
redirect_stderr=true

[program:os1-voice]
command=/root/.local/bin/uv run python -m os1_voice.worker start
directory=/opt/os1/services/voice
environment=HOME="/root",PATH="/root/.local/bin:/usr/local/bin:/usr/bin:/bin"
autorestart=true
stdout_logfile=/var/log/os1-voice.log
redirect_stderr=true

[program:os1-brain]
command=/root/.local/bin/uv run uvicorn os1_voice.brain_server:app --host 127.0.0.1 --port 8788
directory=/opt/os1/services/voice
environment=HOME="/root",PATH="/root/.local/bin:/usr/local/bin:/usr/bin:/bin"
autorestart=true
stdout_logfile=/var/log/os1-brain.log
redirect_stderr=true

; Public HTTPS (Cloudflare quick tunnels: no account needed, URL changes if the tunnel restarts).
[program:os1-tunnel-orchestrator]
command=/usr/local/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8787
autorestart=true
stdout_logfile=/var/log/os1-tunnel-orchestrator.log
redirect_stderr=true

[program:os1-tunnel-brain]
command=/usr/local/bin/cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8788
autorestart=true
stdout_logfile=/var/log/os1-tunnel-brain.log
redirect_stderr=true
"""


def tunnel_urls() -> dict[str, str]:
    out = run(
        "for t in orchestrator brain; do echo \"$t $(grep -oE 'https://[a-z0-9-]+\\.trycloudflare\\.com' "
        "/var/log/os1-tunnel-$t.log | tail -1)\"; done"
    )
    return dict(line.split(" ", 1) for line in out.strip().splitlines() if " https://" in line)


def _update_env_file_atomically(path: Path, updates: dict[str, str]) -> None:
    text = path.read_text()
    for key, val in updates.items():
        line = f"{key}={val}"
        text = re.sub(rf"(?m)^{re.escape(key)}=.*$", line, text) if re.search(rf"(?m)^{re.escape(key)}=", text) else text + "\n" + line
    tmp = path.with_suffix(".env.tmp")
    tmp.write_text(text)
    tmp.replace(path)


def deploy(*, apply: bool) -> None:
    data, count = bundle()
    computer = env("ORGO_COMPUTER_ID") or "<unset>"
    print(
        f"WARNING: Live deploy targets Orgo VM ({computer}). Applying will upload {count} files "
        f"({len(data) // 1024} KB, including .env), overwrite /opt/os1 & /root/.hermes/config.yaml, "
        "and restart all running OS1/Hermes services."
    )
    if not apply:
        print("DRY RUN: no remote changes made. Re-run with `--apply` to execute live deploy.")
        return

    print("uploading bundle…")
    upload(data, "/root/os1-deploy.tgz")
    conf = base64.b64encode(SUPERVISOR.encode()).decode()
    print(
        run(
            f"""set -euo pipefail
export PATH=/root/.local/bin:$PATH
mkdir -p /opt/os1 && tar xzf /root/os1-deploy.tgz -C /opt/os1 && chmod 600 /opt/os1/.env
command -v uv >/dev/null || (curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1)
command -v cloudflared >/dev/null || (curl -sSL -o /usr/local/bin/cloudflared \\
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && chmod +x /usr/local/bin/cloudflared)
(cd /opt/os1/services/orchestrator && uv sync -q --frozen)
(cd /opt/os1/services/voice && uv sync -q --frozen)
cp /opt/os1/hermes/profile/config.yaml /root/.hermes/config.yaml
cp /opt/os1/hermes/profile/SOUL.md /root/.hermes/SOUL.md
mkdir -p /root/.hermes/plugins
cp -r /opt/os1/hermes/plugins/* /root/.hermes/plugins/
echo {shlex.quote(conf)} | base64 -d > /etc/supervisor/conf.d/os1.conf
rm -f /etc/supervisor/conf.d/os1-tunnel.conf
supervisorctl reread >/dev/null; supervisorctl update >/dev/null
supervisorctl restart hermes-gateway os1-orchestrator os1-voice os1-brain >/dev/null
sleep 20; supervisorctl status | grep -E 'hermes-gateway|os1'"""
        )
    )
    urls = tunnel_urls()
    print("public URLs:", urls)
    previous_brain = env("BRAIN_PUBLIC_URL")
    updates = {
        key: urls[name]
        for key, name in (("ORCHESTRATOR_PUBLIC_URL", "orchestrator"), ("BRAIN_PUBLIC_URL", "brain"))
        if name in urls
    }
    if updates:
        _update_env_file_atomically(ENV_PATH, updates)
        payload = base64.b64encode(json.dumps(updates).encode()).decode()
        run(
            f"python3 -c 'import base64,json,re,pathlib; p=pathlib.Path(\"/opt/os1/.env\"); t=p.read_text(); "
            f"u=json.loads(base64.b64decode({payload!r})); "
            f"[t:=re.sub(rf\"(?m)^{{re.escape(k)}}=.*$\",f\"{{k}}={{v}}\",t) if re.search(rf\"(?m)^{{re.escape(k)}}=\",t) else t+f\"\\n{{k}}={{v}}\" for k,v in u.items()]; "
            f"p.write_text(t)'"
        )
    run("supervisorctl restart os1-orchestrator >/dev/null")
    if env("FISH_AGENT_ID") and urls.get("brain") and urls["brain"] != previous_brain:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "fish_live3_agent.py"), urls["brain"]], check=False)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "run":
        print(f"WARNING: Running remote shell command on live Orgo VM ({env('ORGO_COMPUTER_ID')}).", file=sys.stderr)
        print(run(sys.argv[2]))
    else:
        deploy(apply="--apply" in sys.argv[1:])
