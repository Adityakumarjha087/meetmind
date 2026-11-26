from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import auth, upload_demo


def test_upload_runs_full_pipeline(client: TestClient, owner: dict[str, str]) -> None:
    created = upload_demo(client, owner)
    detail = client.get(f"/api/v1/meetings/{created['id']}", headers=auth(owner)).json()
    assert detail["status"] == "completed", detail.get("error")
    assert detail["progress"] == 100
    assert detail["duration_s"] > 60
    assert len(detail["speakers"]) == 3
    assert set(detail["stage_timings"]) >= {"normalize", "transcribe", "diarize", "summarize", "index"}
    insights = detail["insights"]
    assert len(insights["action_items"]) == 4
    assert len(insights["decisions"]) == 2
    assert insights["open_questions"]
    assert detail["audio_url"] and "token=" in detail["audio_url"]
    assert len(detail["waveform_peaks"]) == 800

    transcript = client.get(f"/api/v1/meetings/{created['id']}/transcript", headers=auth(owner)).json()
    assert len(transcript) == 13
    assert {s["speaker_name"] for s in transcript} == {"Speaker 1", "Speaker 2", "Speaker 3"}

    items = client.get(f"/api/v1/workspaces/{owner['workspace_id']}/action-items", headers=auth(owner)).json()
    assert len(items) == 4
    assert all(i["meeting_title"] == "Q3 Launch Planning" for i in items)
