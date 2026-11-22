"""Lean Vercel Serverless entrypoint for Samantha OS¹ voice brain (`brain_server:app`).

Avoids bundling the ~500 MB LiveKit local-inference/onnxruntime worker dependencies
(which run on the Hostinger VPS) while serving the exact same FastAPI brain endpoints
(`/v1/chat/completions`, `/os1/sessions/{id}/poll`, `/voice/health`) on Vercel.
"""

from __future__ import annotations

import sys
from pathlib import Path

_VOICE_ROOT = Path(__file__).resolve().parents[1] / "voice"
if str(_VOICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_VOICE_ROOT))

from os1_voice.brain_server import app  # noqa: E402, F401
