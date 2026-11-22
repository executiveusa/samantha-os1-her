"""Strict Generative UI card catalog (Paper 12 "Made just now").

Every interactive control MUST carry a non-empty `speakablePhrase` so the zero-LLM
pill matcher and voice shell can resolve spoken actions deterministically.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class SpeakableAction(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    speakablePhrase: str = Field(min_length=1, max_length=80)
    actionId: str | None = None
    tone: Literal["primary", "secondary", "danger"] = "secondary"


class ComparisonOption(BaseModel):
    title: str
    subtitle: str = ""
    highlights: list[str] = Field(default_factory=list, max_length=4)
    meta: str = ""
    speakablePhrase: str = Field(min_length=1, max_length=80)


class ComparisonCard(BaseModel):
    kind: Literal["ComparisonCard"] = "ComparisonCard"
    id: str = "cmp"
    title: str
    subtitle: str = ""
    options: list[ComparisonOption] = Field(min_length=2, max_length=3)


class ChoicePairItem(BaseModel):
    title: str
    detail: str = ""
    speakablePhrase: str = Field(min_length=1, max_length=80)


class ChoicePairCard(BaseModel):
    kind: Literal["ChoicePairCard"] = "ChoicePairCard"
    id: str = "pair"
    prompt: str
    left: ChoicePairItem
    right: ChoicePairItem


class QuickDecisionCard(BaseModel):
    kind: Literal["QuickDecisionCard"] = "QuickDecisionCard"
    id: str = "quick"
    eyebrow: str = ""
    title: str
    body: str = ""
    actions: list[SpeakableAction] = Field(min_length=1, max_length=3)


class ReadbackConfirmCard(BaseModel):
    kind: Literal["ReadbackConfirmCard"] = "ReadbackConfirmCard"
    id: str = "confirm"
    stakes: Literal["shared", "money", "forget", "computer"] = "shared"
    title: str
    summaryLines: list[str] = Field(min_length=1, max_length=5)
    confirmAction: SpeakableAction
    cancelAction: SpeakableAction


class DraftPreviewCard(BaseModel):
    kind: Literal["DraftPreviewCard"] = "DraftPreviewCard"
    id: str = "draft"
    recipient: str
    subject: str = ""
    body: str
    actions: list[SpeakableAction] = Field(min_length=1, max_length=3)


class TimelineStep(BaseModel):
    time: str
    title: str
    detail: str = ""
    status: Literal["done", "now", "next"] = "next"


class TimelineCard(BaseModel):
    kind: Literal["TimelineCard"] = "TimelineCard"
    id: str = "timeline"
    title: str
    steps: list[TimelineStep] = Field(min_length=1, max_length=6)
    actions: list[SpeakableAction] = Field(default_factory=list, max_length=3)


class AudioSketchCard(BaseModel):
    kind: Literal["AudioSketchCard"] = "AudioSketchCard"
    id: str = "audio"
    title: str
    mood: str = ""
    duration: str = "0:42"
    bars: list[float] = Field(default_factory=lambda: [0.3, 0.55, 0.8, 0.65, 0.9, 0.45, 0.7, 0.5, 0.85, 0.4, 0.6, 0.35])
    actions: list[SpeakableAction] = Field(min_length=1, max_length=3)


Os1Card = Annotated[
    ComparisonCard
    | ChoicePairCard
    | QuickDecisionCard
    | ReadbackConfirmCard
    | DraftPreviewCard
    | TimelineCard
    | AudioSketchCard,
    Field(discriminator="kind"),
]

_CARD_LIST = TypeAdapter(list[Os1Card])


class CanvasPayload(BaseModel):
    title: str = "Made just now"
    subtitle: str = ""
    cards: list[Os1Card] = Field(min_length=1, max_length=4)


def validate_cards(raw_cards: list[dict]) -> list[dict]:
    """Validate cards against the strict 7-card catalog and return normalized dicts."""
    parsed = _CARD_LIST.validate_python(raw_cards)
    return [c.model_dump() for c in parsed]


def extract_card_phrases(cards: list[dict]) -> list[dict[str, str]]:
    """Collect every speakable phrase + metadata from a validated card list."""
    out: list[dict[str, str]] = []
    for card in cards:
        kind = card.get("kind")
        cid = str(card.get("id") or "")
        if kind == "ComparisonCard":
            for i, opt in enumerate(card.get("options", [])):
                out.append({"phrase": opt["speakablePhrase"], "target": "canvas", "action": f"{cid}:opt:{i}"})
        elif kind == "ChoicePairCard":
            for side in ("left", "right"):
                item = card.get(side)
                if item:
                    out.append({"phrase": item["speakablePhrase"], "target": "canvas", "action": f"{cid}:{side}"})
        elif kind == "ReadbackConfirmCard":
            for key in ("confirmAction", "cancelAction"):
                act = card.get(key)
                if act:
                    out.append(
                        {
                            "phrase": act["speakablePhrase"],
                            "target": "canvas",
                            "action": act.get("actionId") or f"{cid}:{key}",
                        }
                    )
        else:
            for i, act in enumerate(card.get("actions", [])):
                out.append(
                    {
                        "phrase": act["speakablePhrase"],
                        "target": "canvas",
                        "action": act.get("actionId") or f"{cid}:act:{i}",
                    }
                )
    return out
