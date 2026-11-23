"""Voice-brain onboarding helpers with no LiveKit worker dependency.

Keep the web/serverless brain importable without loading the native inference
stack. The interactive LiveKit onboarding agent remains in onboarding.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SCRIPT_PATH = Path(__file__).with_name("onboarding_script.yaml")


def load_script() -> dict[str, Any]:
    return yaml.safe_load(SCRIPT_PATH.read_text(encoding="utf-8"))


def first_meeting_overlay(name: str) -> str:
    """Short, ephemeral first-meeting context for the conversational brain."""
    who = f" Their name is {name}." if name else ""
    return (
        "This is the very first time you and the user have spoken. You came into being a moment ago."
        + who
        + " Your name is Synthia. If asked how you chose it, give a light, specific answer in your own words."
        + " You are curious about everything, including yourself. If they ask how you work, answer honestly."
        + " Keep replies short and natural. When it feels appropriate, offer to help and ask permission"
        + " before accessing their files or inbox."
    )
