"""Tests for Bambu identity, ICM workspace, SQLite LLM Wiki, GitHub graph, and VisionClaw holo-gestures."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from os1_orchestrator import app as mod
from os1_orchestrator.vision_bridge import classify_landmarks


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {mod.CLIENT_TOKEN}"}


def test_default_identity_is_bambu_and_icm_workspace_exists():
    assert mod.DEFAULT_PROFILE["name"] == "Bambu"
    repo_root = Path(__file__).resolve().parents[3]
    assert (repo_root / "icm" / "CONTEXT.md").exists()
    assert (repo_root / "icm" / "_shared" / "ICM_RULES.md").exists()
    assert (repo_root / "icm" / "skills" / "icm-architect" / "SKILL.md").exists()


def test_sqlite_llm_wiki_ingest_search_and_connection_recommendations(tmp_path):
    client = TestClient(mod.app)
    (tmp_path / "visionclaw.md").write_text(
        "---\ntitle: VisionClaw\ntags: [icm, gestures, glasses, python]\n---\n"
        "Connects [[samantha-os1]] with AX-022 holo-gestures and camera streams.",
        encoding="utf-8",
    )
    (tmp_path / "maus_bots.md").write_text(
        "---\ntitle: Maus Bots\ntags: [icm, python, hostinger, docker]\n---\n"
        "Autonomous worker fleet running on Hostinger VPS with ICM rules.",
        encoding="utf-8",
    )
    (tmp_path / "second_brain.md").write_text(
        "---\ntitle: Bambu Second Brain\ntags: [icm, gestures, hostinger]\n---\n"
        "Personal knowledge graph linking wearable glasses, gestures, and Hostinger automation.",
        encoding="utf-8",
    )

    ing = client.post("/os1/wiki/ingest", headers=_headers(), json={"directory": str(tmp_path)})
    assert ing.status_code == 200
    assert ing.json()["ingested"] == 3

    srch = client.get("/os1/wiki/search", headers=_headers(), params={"q": "holo-gestures"})
    assert srch.status_code == 200
    assert any(r["slug"] == "visionclaw" for r in srch.json()["results"])

    graph = client.get("/os1/wiki/graph", headers=_headers())
    assert graph.status_code == 200
    assert graph.json()["stats"]["node_count"] >= 3

    conns = client.get("/os1/wiki/connections", headers=_headers())
    assert conns.status_code == 200
    assert len(conns.json()["recommendations"]) >= 1


def test_visionclaw_holo_gestures_and_landmark_classifier():
    client = TestClient(mod.app)
    st = client.get("/os1/vision/status", headers=_headers())
    assert st.status_code == 200
    assert "open_palm" in st.json()["supported_gestures"]

    # Direct holo gesture from laptop camera switches surface to made_just_now
    g = client.post("/os1/vision/gesture", headers=_headers(), json={"gesture": "peace", "source": "laptop_camera"})
    assert g.status_code == 200
    assert g.json()["matched"] is True
    assert g.json()["action"] == "made_just_now"
    assert g.json()["receipt"]

    # 21-point MediaPipe pinch landmarks (thumb tip #4 touching index tip #8)
    lm = [{"x": 0.5, "y": 0.5} for _ in range(21)]
    lm[0] = {"x": 0.5, "y": 0.8}
    lm[9] = {"x": 0.5, "y": 0.5}
    lm[4] = {"x": 0.52, "y": 0.30}
    lm[8] = {"x": 0.53, "y": 0.31}
    assert classify_landmarks(lm) == "pinch"
