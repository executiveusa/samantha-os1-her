#!/usr/bin/env bash
# Install (or refresh) the `samantha` Hermes profile & OS1 plugins from this repo.
# Usage: hermes/install-profile.sh [path-to-repo-.env]
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo_env="${1:-$here/../.env}"
hermes_root="${HERMES_HOME_ROOT:-${HOME:?HOME must be set}/.hermes}"
dest="${hermes_root}/profiles/samantha"

mkdir -p "$dest" "${hermes_root}/plugins"
real_root="$(realpath "$hermes_root")"
real_dest="$(realpath "$dest")"
case "$real_dest" in
  "$real_root"/*) ;;
  *) echo "Refusing to write outside $real_root (got $real_dest)" >&2; exit 1 ;;
esac

cp "$here/profile/config.yaml" "$dest/config.yaml"
cp "$here/profile/SOUL.md" "$dest/SOUL.md"
cp -r "$here/plugins/"* "${hermes_root}/plugins/"

# Build the profile .env safely via Python (portable macOS/Linux, immune to sed delimiters).
tmp="$(mktemp)"
trap 'rm -f "${tmp:?}"' EXIT
cp "$here/profile/env.example" "$tmp"
if [[ -f "$repo_env" ]]; then
  python3 - "$repo_env" "$tmp" "$dest/config.yaml" <<'PY'
import pathlib, re, sys
repo_env, tmp_env, cfg_path = (pathlib.Path(p) for p in sys.argv[1:4])
src = repo_env.read_text()

def get(k: str) -> str:
    m = re.search(rf"(?m)^{re.escape(k)}=(.*)$", src)
    return m.group(1).split("#")[0].strip() if m else ""

env_out = tmp_env.read_text()
for key in ("API_SERVER_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "FISH_API_KEY"):
    src_key = "HERMES_API_KEY" if key == "API_SERVER_KEY" else key
    val = get(src_key)
    if val:
        env_out = re.sub(rf"(?m)^{re.escape(key)}=.*$", lambda _, k=key, v=val: f"{k}={v}", env_out)
tmp_env.write_text(env_out)

voice = get("FISH_VOICE_1_ID")
if voice:
    cfg_path.write_text(cfg_path.read_text().replace("REPLACE_WITH_FISH_VOICE_1_ID", voice))
PY
fi
install -m 600 "$tmp" "$dest/.env"

echo "Installed profile + OS1 plugins to $dest"
echo "Next: hermes -p samantha gateway run   (API server on 127.0.0.1:8642)"
