"""One-shot end-to-end Fish Live 3 / LiveKit audio smoke test.

Usage (Python 3.12+, livekit installed from services/voice):
  uv run --project services/voice python scripts/smoke_synthia_live3.py

Reads FISH_API_KEY and FISH_AGENT_ID from environment or local gitignored
.vault-staging/generated-secrets.env. Never prints credentials, session URLs
or room tokens. Costs one brief Fish session and a short LLM turn.
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from pathlib import Path

from livekit import rtc

ROOT = Path(__file__).resolve().parents[1]


def config() -> dict[str, str]:
    values: dict[str, str] = dict(os.environ)
    file = Path(os.environ.get("SYNTHIA_SMOKE_ENV_FILE", ROOT / ".vault-staging" / "generated-secrets.env"))
    if file.is_file():
        for line in file.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values.setdefault(key.strip(), value.strip().strip("'\\\""))
    return values


async def main() -> int:
    settings = config()
    if not settings.get("FISH_API_KEY") or not settings.get("FISH_AGENT_ID"):
        print("CONFIG_MISSING: Fish API key and agent ID required")
        return 2

    body = json.dumps({
        "agent_id": settings["FISH_AGENT_ID"],
        "llm_extra_body": {"first_meeting": False, "name": "Voice QA"},
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.fish.audio/v1/agent/sessions",
        data=body,
        headers={"Authorization": f"Bearer {settings['FISH_API_KEY']}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        # One session only; do not retry side effects implicitly.
        with urllib.request.urlopen(request, timeout=20) as response:
            session = json.load(response)
    except Exception as exc:
        print(f"FISH_SESSION_ERROR: {type(exc).__name__}")
        return 1

    url = session.get("livekit_url") or session.get("url")
    token = session.get("token")
    if not (url and token):
        print("FISH_SESSION_MISSING_TRANSPORT")
        return 1
    print("FISH_SESSION: OK")

    room = rtc.Room()
    audio_seen = asyncio.Event()
    count = 0

    async def listen(track: rtc.Track) -> None:
        nonlocal count
        stream = rtc.AudioStream(track)
        async for frame in stream:
            if frame.frame:
                count += 1
                audio_seen.set()
                if count >= 10:
                    break

    @room.on("track_subscribed")
    def subscribed(track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            asyncio.create_task(listen(track))

    try:
        await asyncio.wait_for(room.connect(url, token), timeout=20)
        print("LIVEKIT_CONNECTED: OK")
        for _ in range(30):
            if room.remote_participants:
                break
            await asyncio.sleep(0.3)
        print("REMOTE_PARTICIPANTS:", len(room.remote_participants))
        await room.local_participant.publish_data(
            json.dumps({"type": "user.message", "text": "Hello Synthia. Please say your name and one short greeting."}),
            reliable=True,
            topic="client-event",
        )
        print("TEXT_EVENT_SENT: OK")
        try:
            await asyncio.wait_for(audio_seen.wait(), timeout=22)
        except asyncio.TimeoutError:
            print("REMOTE_AUDIO: TIMEOUT")
            return 1
        print("REMOTE_AUDIO: PASS; frames=", count)
        return 0
    except Exception as exc:
        print(f"LIVEKIT_ERROR: {type(exc).__name__}")
        return 1
    finally:
        await room.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
