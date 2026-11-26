from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import auth, register, upload_demo


def test_board_crud_and_assignment(client: TestClient, owner: dict[str, str]) -> None:
    ws = owner["workspace_id"]
    base = f"/api/v1/workspaces/{ws}/action-items"
    m = upload_demo(client, owner)
    created = client.post(
        base,
        json={"title": "Draft launch FAQ", "meeting_id": m["id"], "due_date": "2026-12-01"},
        headers=auth(owner),
    )
    assert created.status_code == 201
    item = created.json()
    assert item["status"] == "todo" and item["meeting_title"] == "Q3 Launch Planning"

    teammate = register(client, "tm@example.com", "Tina Mate")
    client.post(
        f"/api/v1/workspaces/{ws}/members", json={"email": "tm@example.com"}, headers=auth(owner)
    )
    tm_id = next(
        x["user_id"]
        for x in client.get(f"/api/v1/workspaces/{ws}/members", headers=auth(owner)).json()
        if x["email"] == "tm@example.com"
    )

    upd = client.patch(
        f"/api/v1/action-items/{item['id']}",
        json={"status": "in_progress", "assignee_id": tm_id, "position": 0.5},
        headers=auth(owner),
    )
    assert upd.status_code == 200
    body = upd.json()
    assert (
        body["status"] == "in_progress"
        and body["assignee_name"] == "Tina Mate"
        and body["owner_name"] == "Tina Mate"
    )

    mine = client.get(f"{base}?assignee=me", headers=auth(teammate)).json()
    assert [i["id"] for i in mine] == [item["id"]]
    assert len(client.get(f"{base}?status=in_progress", headers=auth(owner)).json()) == 1
    done = client.patch(
        f"/api/v1/action-items/{item['id']}", json={"status": "done"}, headers=auth(teammate)
    )
    assert done.json()["status"] == "done"

    outsider = register(client, "o@example.com", "Out")
    out_id = client.get("/api/v1/auth/me", headers=auth(outsider)).json()["id"]
    assert (
        client.patch(
            f"/api/v1/action-items/{item['id']}", json={"assignee_id": out_id}, headers=auth(owner)
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/action-items/{item['id']}", json={"title": "x"}, headers=auth(outsider)
        ).status_code
        == 404
    )
    assert (
        client.post(
            base, json={"title": "x", "meeting_id": "missing"}, headers=auth(owner)
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/action-items/{item['id']}", headers=auth(owner)).status_code == 204
    )
    assert (
        client.delete(f"/api/v1/action-items/{item['id']}", headers=auth(owner)).status_code == 404
    )


def test_viewer_cannot_edit_board(client: TestClient, owner: dict[str, str]) -> None:
    upload_demo(client, owner)
    viewer = register(client, "v@example.com", "View")
    client.post(
        f"/api/v1/workspaces/{owner['workspace_id']}/members",
        json={"email": "v@example.com", "role": "viewer"},
        headers=auth(owner),
    )
    items = client.get(
        f"/api/v1/workspaces/{owner['workspace_id']}/action-items", headers=auth(viewer)
    ).json()
    assert len(items) == 4
    assert (
        client.patch(
            f"/api/v1/action-items/{items[0]['id']}", json={"status": "done"}, headers=auth(viewer)
        ).status_code
        == 403
    )
