from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import auth, upload_demo


def test_ask_returns_timestamped_citations(client: TestClient, owner: dict[str, str]) -> None:
    m = upload_demo(client, owner)
    r = client.post(
        f"/api/v1/workspaces/{owner['workspace_id']}/ask",
        json={"question": "What was decided about pricing?"},
        headers=auth(owner),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "offline"
    assert body["citations"], body
    assert "twenty nine dollars" in body["answer"]
    cite = body["citations"][0]
    assert (
        cite["meeting_id"] == m["id"]
        and cite["start_s"] >= 0
        and f"[{cite['index']}]" in body["answer"]
    )


def test_ask_no_match_and_scoped(client: TestClient, owner: dict[str, str]) -> None:
    m = upload_demo(client, owner)
    r = client.post(
        f"/api/v1/workspaces/{owner['workspace_id']}/ask",
        json={"question": "kubernetes helm chart"},
        headers=auth(owner),
    ).json()
    assert r["citations"] == [] and "couldn't find" in r["answer"]
    scoped = client.post(
        f"/api/v1/workspaces/{owner['workspace_id']}/ask",
        json={"question": "press release draft", "meeting_id": m["id"]},
        headers=auth(owner),
    ).json()
    assert all(c["meeting_id"] == m["id"] for c in scoped["citations"])


def test_semantic_search(client: TestClient, owner: dict[str, str]) -> None:
    upload_demo(client, owner)
    hits = client.get(
        f"/api/v1/workspaces/{owner['workspace_id']}/search",
        params={"q": "payment bugs"},
        headers=auth(owner),
    ).json()
    assert hits and "payment" in hits[0]["text"].lower()
    assert hits == sorted(hits, key=lambda h: -h["score"])
    assert (
        client.get(
            f"/api/v1/workspaces/{owner['workspace_id']}/search",
            params={"q": "x"},
            headers=auth(owner),
        ).status_code
        == 422
    )
