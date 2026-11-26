from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import auth, register, upload_demo


def _ws(h: dict[str, str]) -> str:
    return f"/api/v1/workspaces/{h['workspace_id']}"


def test_create_and_update_workspace(client: TestClient, owner: dict[str, str]) -> None:
    resp = client.post("/api/v1/workspaces", json={"name": "Platform Team"}, headers=auth(owner))
    assert resp.status_code == 201 and resp.json()["role"] == "owner"
    new_id = resp.json()["id"]
    assert len(client.get("/api/v1/workspaces", headers=auth(owner)).json()) == 2
    patch = client.patch(
        f"/api/v1/workspaces/{new_id}",
        json={
            "name": "Platform",
            "slack_webhook_url": "https://hooks.slack.com/services/" + "x/y/z",
            "slack_auto_post": True,
        },
        headers=auth(owner),
    )
    assert patch.status_code == 200
    assert patch.json()["slack_configured"] and patch.json()["slack_auto_post"]
    bad = client.patch(
        f"/api/v1/workspaces/{new_id}",
        json={"slack_webhook_url": "https://evil.example.com/x"},
        headers=auth(owner),
    )
    assert bad.status_code == 422
    cleared = client.patch(
        f"/api/v1/workspaces/{new_id}", json={"slack_webhook_url": ""}, headers=auth(owner)
    )
    assert cleared.json()["slack_configured"] is False
    assert client.delete(f"/api/v1/workspaces/{new_id}", headers=auth(owner)).status_code == 204


def test_cannot_delete_only_workspace(client: TestClient, owner: dict[str, str]) -> None:
    assert client.delete(_ws(owner), headers=auth(owner)).status_code == 422


def test_rbac_matrix(client: TestClient, owner: dict[str, str]) -> None:
    member = register(client, "member@example.com", "Mem Ber")
    viewer = register(client, "viewer@example.com", "Vee Wer")
    outsider = register(client, "out@example.com", "Out Sider")
    assert (
        client.post(
            f"{_ws(owner)}/members",
            json={"email": "member@example.com", "role": "member"},
            headers=auth(owner),
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"{_ws(owner)}/members",
            json={"email": "viewer@example.com", "role": "viewer"},
            headers=auth(owner),
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"{_ws(owner)}/members", json={"email": "viewer@example.com"}, headers=auth(owner)
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"{_ws(owner)}/members", json={"email": "ghost@example.com"}, headers=auth(owner)
        ).status_code
        == 404
    )

    meeting = upload_demo(client, owner)
    # outsider sees nothing (404 hides existence)
    assert client.get(f"{_ws(owner)}/meetings", headers=auth(outsider)).status_code == 404
    assert (
        client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth(outsider)).status_code == 404
    )
    # viewer can read but not write
    assert client.get(f"/api/v1/meetings/{meeting['id']}", headers=auth(viewer)).status_code == 200
    assert (
        client.patch(
            f"/api/v1/meetings/{meeting['id']}", json={"title": "x"}, headers=auth(viewer)
        ).status_code
        == 403
    )
    assert client.get(f"{_ws(owner)}/usage", headers=auth(viewer)).status_code == 403
    # member can edit but not delete or manage members
    assert (
        client.patch(
            f"/api/v1/meetings/{meeting['id']}", json={"title": "Renamed"}, headers=auth(member)
        ).status_code
        == 200
    )
    assert (
        client.delete(f"/api/v1/meetings/{meeting['id']}", headers=auth(member)).status_code == 403
    )
    assert (
        client.post(
            f"{_ws(owner)}/members", json={"email": "out@example.com"}, headers=auth(member)
        ).status_code
        == 403
    )
    assert client.patch(_ws(owner), json={"name": "x"}, headers=auth(member)).status_code == 403

    members = client.get(f"{_ws(owner)}/members", headers=auth(viewer)).json()
    assert {m["role"] for m in members} == {"owner", "member", "viewer"}


def test_role_changes_and_owner_protection(client: TestClient, owner: dict[str, str]) -> None:
    admin = register(client, "admin@example.com", "Ad Min")
    client.post(
        f"{_ws(owner)}/members",
        json={"email": "admin@example.com", "role": "admin"},
        headers=auth(owner),
    )
    admin_id = next(
        m["user_id"]
        for m in client.get(f"{_ws(owner)}/members", headers=auth(owner)).json()
        if m["role"] == "admin"
    )
    owner_id = next(
        m["user_id"]
        for m in client.get(f"{_ws(owner)}/members", headers=auth(owner)).json()
        if m["role"] == "owner"
    )

    # admins cannot grant/alter owner roles
    assert (
        client.patch(
            f"{_ws(owner)}/members/{owner_id}", json={"role": "member"}, headers=auth(admin)
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"{_ws(owner)}/members",
            json={"email": "admin@example.com", "role": "owner"},
            headers=auth(admin),
        ).status_code
        == 403
    )
    # last owner cannot demote or remove themselves
    assert (
        client.patch(
            f"{_ws(owner)}/members/{owner_id}", json={"role": "admin"}, headers=auth(owner)
        ).status_code
        == 422
    )
    assert client.delete(f"{_ws(owner)}/members/{owner_id}", headers=auth(owner)).status_code == 422
    assert (
        client.patch(
            f"{_ws(owner)}/members/missing", json={"role": "admin"}, headers=auth(owner)
        ).status_code
        == 404
    )
    # promote, then demote; admin can leave voluntarily
    assert (
        client.patch(
            f"{_ws(owner)}/members/{admin_id}", json={"role": "member"}, headers=auth(owner)
        ).json()["role"]
        == "member"
    )
    assert client.delete(f"{_ws(owner)}/members/{admin_id}", headers=auth(admin)).status_code == 204
    assert client.get(_ws(owner), headers=auth(admin)).status_code == 404


def test_usage_dashboard(client: TestClient, owner: dict[str, str]) -> None:
    upload_demo(client, owner)
    data = client.get(f"{_ws(owner)}/usage?days=7", headers=auth(owner)).json()
    t = data["totals"]
    assert t["meetings_processed"] == 1
    assert 1.2 < t["minutes_transcribed"] < 1.3
    assert t["avg_processing_seconds"] > 0 and t["avg_realtime_factor"] > 0
    assert t["llm_input_tokens"] > 0
    assert t["cost_usd"] == 0.0 and t["projected_hosted_cost_usd"] > 0
    assert len(data["daily"]) == 7
    assert {r["kind"] for r in data["by_provider"]} == {"stt", "diarization", "llm", "embedding"}
    assert "diarize" in data["stage_seconds"]
    integ = client.get(f"{_ws(owner)}/integrations", headers=auth(owner)).json()
    assert integ["llm_provider"] == "offline" and integ["google_oauth_enabled"] is False
