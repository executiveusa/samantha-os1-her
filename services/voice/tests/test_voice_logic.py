"""Offline tests: no LiveKit, Fish, Hermes or Jev keys needed."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from os1_voice.cues import strip_cues, strip_cues_stream
from os1_voice.onboarding import Dossier, judge_hesitant, judge_voice, load_script
from os1_voice.router import Route, RunRef, TurnRouter


def run(coro):
    return asyncio.run(coro)


async def collect(chunks):
    async def gen():
        for c in chunks:
            yield c

    return "".join([x async for x in strip_cues_stream(gen())])


# --- cues -------------------------------------------------------------------


def test_strip_cues_keeps_words():
    assert strip_cues("[softly, amused] Okay, [small laugh] I have to hear it.") == "Okay, I have to hear it."


def test_strip_cues_stream_handles_split_brackets():
    assert run(collect(["[soft", "ly] Hello, I'm ", "here. [small ", "laugh] Hi."])) == "Hello, I'm here. Hi."


def test_strip_cues_leaves_long_brackets():
    long = "[" + "x" * 120 + "]"
    assert strip_cues(long) == long


# --- router -----------------------------------------------------------------


class FakeJev:
    def __init__(self, answers=None):
        self.answers = answers
        self.calls = 0

    async def ask(self, state, questions, budget_s=None):
        self.calls += 1
        return None if self.answers is None else SimpleNamespace(answers=self.answers)


def choice(winner, probs):
    return SimpleNamespace(choice=winner, probabilities=probs)


def test_exact_chip_skips_jev():
    jev = FakeJev()
    route = run(TurnRouter(jev).route("hold on a sec!", recent=[], chips=["Hold on a sec"], runs=[]))
    assert route == Route(kind="chip", confidence=1.0, chip="Hold on a sec", source="exact")
    assert jev.calls == 0


def test_jev_down_falls_back_to_chat():
    route = run(TurnRouter(FakeJev(None)).route("how are you", recent=[], chips=[], runs=[]))
    assert route.kind == "chat" and route.source == "fallback"


def test_work_threshold_is_permissive():
    answers = {
        "kind": choice("chat", {"chat": 0.52, "work": 0.48}),
        "addressed": SimpleNamespace(noul=0.9),
        "warmth": SimpleNamespace(score=1.0),
    }
    route = run(TurnRouter(FakeJev(answers)).route("check my email", recent=[], chips=[], runs=[]))
    assert route.kind == "work"


def test_not_addressed_is_ignored():
    answers = {
        "kind": choice("chat", {"chat": 0.9, "work": 0.1}),
        "addressed": SimpleNamespace(noul=0.05),
        "warmth": SimpleNamespace(score=1.0),
    }
    route = run(TurnRouter(FakeJev(answers)).route("honey, dinner's ready", recent=[], chips=[], runs=[]))
    assert route.kind == "ignore"


def test_control_targets_run():
    runs = [RunRef("r1", "clean up inbox"), RunRef("r2", "book the ferry")]
    answers = {
        "kind": choice("control", {"chat": 0.1, "work": 0.1, "control": 0.8}),
        "addressed": SimpleNamespace(noul=0.95),
        "warmth": SimpleNamespace(score=0.5),
        "control_target": choice("run_1", {"run_0": 0.1, "run_1": 0.9}),
        "control_action": choice("stop", {"stop": 0.9}),
    }
    route = run(TurnRouter(FakeJev(answers)).route("stop the ferry thing", recent=[], chips=[], runs=runs))
    assert (route.kind, route.run_id, route.control) == ("control", "r2", "stop")


# --- onboarding ---------------------------------------------------------------


def test_script_has_every_line():
    script = load_script()
    for key in ["welcome", "q1_social", "q1_hesitance", "q2_voice", "q3_mother", "q3_cutoff", "handoff"]:
        assert script["operator"][key]
    assert "{name}" in script["operator"]["welcome"]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("Um, I guess, I don't know, kind of social?", True), ("Social. Definitely.", False)],
)
def test_hesitance_fallback(answer, expected):
    assert run(judge_hesitant(FakeJev(None), answer)) is expected


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("Female", "female"), ("a man's voice please", "male"), ("you choose", "surprise"), ("hmm", None)],
)
def test_voice_fallback(answer, expected):
    assert run(judge_voice(FakeJev(None), answer, ["Female", "Male", "Surprise me"])) == expected


def test_dossier_memory_text():
    d = Dossier(name="Theo", social="Not really", hesitant=True, mother="Well, she")
    text = d.as_memory_text()
    assert "Theo" in text and "hesitant" in text and "cut off" in text


def test_hermes_sse_event_name_inside_json():
    import httpx

    from os1_voice.config import Settings
    from os1_voice.hermes import HermesRuns

    body = (
        'id: 1\ndata: {"event": "message.delta", "delta": "Hi"}\n\n'
        ": keepalive\n\n"
        'data: {"event": "run.completed", "output": "done"}\n\n'
    )
    runs = HermesRuns(Settings())
    runs._http = httpx.AsyncClient(
        base_url="http://hermes", transport=httpx.MockTransport(lambda req: httpx.Response(200, text=body))
    )

    async def collect():
        return [(e.event, e.data.get("output")) async for e in runs.events("r1")]

    assert run(collect()) == [("message.delta", None), ("run.completed", "done")]
