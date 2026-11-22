"""VisionClaw AX-022 Eyes, Ears & Hands Bridge + Holo-Gestures Engine for Samantha OS¹.

Integrates `executiveusa/VisionClaw` (AX-022 wearable/glasses gateway + holo-gestures)
with OS¹ so Samantha can receive:
1. Smart-glasses camera/gesture streams via VisionClaw AX-022 Gateway (`VISIONCLAW_GATEWAY_URL`)
2. Direct laptop webcam frames & MediaPipe 21-point hand landmarks from OS¹ Desktop / Web PWA
3. Holo Commands & hand gestures mapped deterministically to OS¹ actions under ICM L0-L4 policy:
   - `open_palm`   → L1 safety stop (`cua:revoke` / "Let me drive")
   - `pinch`       → Select / confirm active card or pill
   - `tap`         → Acknowledge / push-to-talk trigger
   - `peace`       → Open Generative UI Canvas (`made_just_now`)
   - `point`       → Inspect cloud computer / Vision POV (`her_computer`)
   - `fist`        → Dismiss to calm coral conversation horizon (`conversation`)
   - `flick_right` → Next OS¹ surface
   - `flick_left`  → Previous OS¹ surface
   - `stretch`     → Expand Swarm & Knowledge Graph (`swarm`)
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import time
from typing import Any

SURFACE_CYCLE = ("conversation", "home", "inbox_cascade", "swarm", "memory", "made_just_now", "her_computer")

GESTURE_TO_ACTION: dict[str, dict[str, Any]] = {
    "open_palm": {"target": "cua", "action": "revoke", "policy": "L1", "reply": "Open palm detected — hands off, you have control."},
    "pinch": {"target": "holo", "action": "select", "policy": "L1", "reply": "Selected."},
    "tap": {"target": "holo", "action": "ack", "policy": "L0", "reply": "Listening."},
    "peace": {"target": "surface", "action": "made_just_now", "policy": "L0", "reply": "Opening canvas."},
    "point": {"target": "surface", "action": "her_computer", "policy": "L0", "reply": "Opening vision view."},
    "fist": {"target": "surface", "action": "conversation", "policy": "L0", "reply": "Clearing screen."},
    "stretch": {"target": "surface", "action": "swarm", "policy": "L0", "reply": "Expanding swarm view."},
    "flick_right": {"target": "surface_cycle", "action": "next", "policy": "L0", "reply": "Next surface."},
    "flick_left": {"target": "surface_cycle", "action": "prev", "policy": "L0", "reply": "Previous surface."},
}


def _dist(a: dict[str, float], b: dict[str, float]) -> float:
    return math.hypot(a.get("x", 0.0) - b.get("x", 0.0), a.get("y", 0.0) - b.get("y", 0.0))


def classify_landmarks(landmarks: list[dict[str, float]]) -> str | None:
    """Classify a single hand's 21 MediaPipe landmarks into a VisionClaw holo-gesture (L0)."""
    if len(landmarks) < 21:
        return None
    wrist = landmarks[0]
    thumb_tip, index_tip, middle_tip, ring_tip, pinky_tip = (
        landmarks[4], landmarks[8], landmarks[12], landmarks[16], landmarks[20]
    )
    index_pip, middle_pip, ring_pip, pinky_pip = landmarks[6], landmarks[10], landmarks[14], landmarks[18]

    palm_scale = max(_dist(wrist, landmarks[9]), 1e-4)
    pinch_ratio = _dist(thumb_tip, index_tip) / palm_scale

    index_up = _dist(index_tip, wrist) > _dist(index_pip, wrist) * 1.12
    middle_up = _dist(middle_tip, wrist) > _dist(middle_pip, wrist) * 1.12
    ring_up = _dist(ring_tip, wrist) > _dist(ring_pip, wrist) * 1.12
    pinky_up = _dist(pinky_tip, wrist) > _dist(pinky_pip, wrist) * 1.12

    if pinch_ratio < 0.34:
        return "pinch"
    if index_up and middle_up and ring_up and pinky_up:
        return "open_palm"
    if index_up and middle_up and not ring_up and not pinky_up:
        return "peace"
    if index_up and not middle_up and not ring_up and not pinky_up:
        return "point"
    if not index_up and not middle_up and not ring_up and not pinky_up:
        return "fist"
    return None


class VisionClawBridge:
    def __init__(self) -> None:
        self.gateway_url = os.environ.get("VISIONCLAW_GATEWAY_URL", "http://127.0.0.1:4022").rstrip("/")
        self.recent_events: list[dict[str, Any]] = []
        self.last_frame_meta: dict[str, Any] | None = None

    def _sign_receipt(self, gesture: str, source: str, ts: float) -> str:
        secret = (os.environ.get("OS1_CLIENT_TOKEN") or "os1-visionclaw-dev").encode("utf-8")
        msg = f"{gesture}:{source}:{int(ts)}".encode()
        return hmac.new(secret, msg, hashlib.sha256).hexdigest()[:24]

    def status(self) -> dict[str, Any]:
        return {
            "gateway_url": self.gateway_url,
            "supported_sources": ["laptop_camera", "meta_rayban", "brilliant_halo", "mentra_live", "holo_command"],
            "supported_gestures": sorted(GESTURE_TO_ACTION.keys()),
            "last_frame": self.last_frame_meta,
            "recent_events": self.recent_events[-10:],
        }

    def record_frame(self, *, source: str, width: int = 0, height: int = 0, summary: str = "") -> dict[str, Any]:
        self.last_frame_meta = {
            "source": source,
            "width": width,
            "height": height,
            "summary": summary[:280],
            "received_at": time.time(),
        }
        return self.last_frame_meta

    def resolve_gesture(
        self,
        *,
        gesture: str | None = None,
        landmarks: list[dict[str, float]] | None = None,
        source: str = "laptop_camera",
        active_surface: str = "conversation",
    ) -> dict[str, Any]:
        detected = (gesture or "").strip().lower()
        if not detected and landmarks:
            detected = classify_landmarks(landmarks) or ""
        if detected not in GESTURE_TO_ACTION:
            return {"matched": False, "gesture": detected or None, "source": source}

        mapping = dict(GESTURE_TO_ACTION[detected])
        target = mapping["target"]
        action = mapping["action"]
        if target == "surface_cycle":
            idx = SURFACE_CYCLE.index(active_surface) if active_surface in SURFACE_CYCLE else 0
            nxt = SURFACE_CYCLE[(idx + (1 if action == "next" else -1)) % len(SURFACE_CYCLE)]
            target, action = "surface", nxt

        ts = time.time()
        event = {
            "matched": True,
            "gesture": detected,
            "source": source,
            "target": target,
            "action": action,
            "policy": mapping["policy"],
            "reply": mapping["reply"],
            "receipt": self._sign_receipt(detected, source, ts),
            "ts": ts,
        }
        self.recent_events.append(event)
        self.recent_events = self.recent_events[-50:]
        return event
