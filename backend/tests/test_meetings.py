from __future__ import annotations

import io
import json
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.db.session import session_scope
from app.models import Meeting, MeetingSource, MeetingStatus
from tests.conftest import DEMO_WAV, auth, upload_demo


def test_upload_validation(client: TestClient, owner: dict[str, str]) -> None:
    url = f"/api/v1/workspaces/{owner['workspace_id']}/meetings"
    r = client.post(
        url, headers=auth(owner), files={"file": ("notes.pdf", b"%PDF", "application/pdf")}
    )
    assert r.status_code == 422 and "Unsupported file type" in r.json()["error"]["message"]
    r = client.post(url, headers=auth(owner), files={"file": ("a.wav", b"", "audio/wav")})
    assert r.status_code == 422 and "empty" in r.json()["error"]["message"]
    r = client.post(url, headers=auth(owner), files={"file": ("a.wav", b"RIFF", "text/html")})
    assert r.status_code == 422
    r = client.post(
        url,
        headers=auth(owner),
        files={
            "file": ("a.wav", DEMO_WAV.read_bytes(), "audio/wav"),
            "transcript": ("t.docx", b"x", "application/octet-stream"),
        },
    )
    assert r.status_code == 422


def test_non_wav_without_ffmpeg_fails_gracefully(client: TestClient, owner: dict[str, str]) -> None:
    url = f"/api/v1/workspaces/{owner['workspace_id']}/meetings"
    r = client.post(
        url, headers=auth(owner), files={"file": ("clip.mp3", b"ID3fakeaudio" * 100, "audio/mpeg")}
    )
    assert r.status_code == 201
    detail = client.get(f"/api/v1/meetings/{r.json()['id']}", headers=auth(owner)).json()
    assert detail["status"] == "failed" and "FFmpeg" in detail["error"]
    assert detail["stage"] == "failed"


def test_list_filter_and_search(client: TestClient, owner: dict[str, str]) -> None:
    upload_demo(client, owner)
    upload_demo(client, owner, title="Board prep")
    base = f"/api/v1/workspaces/{owner['workspace_id']}/meetings"
    page = client.get(base, headers=auth(owner)).json()
    assert page["total"] == 2 and page["items"][0]["action_item_count"] == 4
    assert client.get(f"{base}?q=board", headers=auth(owner)).json()["total"] == 1
    assert client.get(f"{base}?status=failed", headers=auth(owner)).json()["total"] == 0
    assert client.get(f"{base}?limit=1", headers=auth(owner)).json()["items"].__len__() == 1


def test_sidecar_vtt_with_speaker_names(client: TestClient, owner: dict[str, str]) -> None:
    segs = json.loads(
        (DEMO_WAV.parent.parent / "fixtures" / "transcripts").glob("*.json").__next__().read_text()
    )["segments"]
    names = [
        "Priya",
        "Marcus",
        "Priya",
        "Marcus",
        "Raj",
        "Priya",
        "Raj",
        "Marcus",
        "Priya",
        "Marcus",
        "Priya",
        "Raj",
        "Priya",
    ]

    def ts(x: float) -> str:
        m, s = divmod(x, 60)
        return f"00:{int(m):02d}:{s:06.3f}"

    vtt = "WEBVTT\n\n" + "\n\n".join(
        f"{ts(s['start'])} --> {ts(s['end'])}\n<v {n}>{s['text']}</v>"
        for s, n in zip(segs, names, strict=True)
    )
    with DEMO_WAV.open("rb") as fh:
        r = client.post(
            f"/api/v1/workspaces/{owner['workspace_id']}/meetings",
            headers=auth(owner),
            files={
                "file": ("standup.wav", fh, "audio/wav"),
                "transcript": ("standup.vtt", vtt.encode(), "text/vtt"),
            },
        )
    detail = client.get(f"/api/v1/meetings/{r.json()['id']}", headers=auth(owner)).json()
    assert detail["title"] == "standup"
    assert sorted(s["display_name"] for s in detail["speakers"]) == ["Marcus", "Priya", "Raj"]
    owners = {a["owner"] for a in detail["insights"]["action_items"]}
    assert owners == {"Marcus", "Raj"}


def test_rename_speaker_propagates(client: TestClient, owner: dict[str, str]) -> None:
    m = upload_demo(client, owner)
    detail = client.get(f"/api/v1/meetings/{m['id']}", headers=auth(owner)).json()
    speaker2 = next(s for s in detail["speakers"] if s["display_name"] == "Speaker 2")
    r = client.patch(
        f"/api/v1/meetings/{m['id']}/speakers/{speaker2['id']}",
        json={"display_name": "Marcus"},
        headers=auth(owner),
    )
    assert r.status_code == 200 and r.json()["display_name"] == "Marcus"
    items = client.get(
        f"/api/v1/workspaces/{owner['workspace_id']}/action-items", headers=auth(owner)
    ).json()
    assert sum(i["owner_name"] == "Marcus" for i in items) == 2
    detail = client.get(f"/api/v1/meetings/{m['id']}", headers=auth(owner)).json()
    assert "Marcus" in {s["speaker"] for s in detail["insights"]["sentiment"]}
    transcript = client.get(f"/api/v1/meetings/{m['id']}/transcript", headers=auth(owner)).json()
    assert "Marcus" in {t["speaker_name"] for t in transcript}
    assert (
        client.patch(
            f"/api/v1/meetings/{m['id']}/speakers/nope",
            json={"display_name": "X"},
            headers=auth(owner),
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/meetings/{m['id']}/speakers/{speaker2['id']}",
            json={"display_name": "   "},
            headers=auth(owner),
        ).status_code
        == 422
    )


def test_audio_streaming_with_media_token(client: TestClient, owner: dict[str, str]) -> None:
    m = upload_demo(client, owner)
    detail = client.get(f"/api/v1/meetings/{m['id']}", headers=auth(owner)).json()
    parsed = urlparse(detail["audio_url"])
    token = parse_qs(parsed.query)["token"][0]
    path = parsed.path
    full = client.get(path, params={"token": token})
    assert full.status_code == 200 and full.headers["content-type"] == "audio/wav"
    assert full.content[:4] == b"RIFF"
    part = client.get(path, params={"token": token}, headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100
    assert part.headers["content-range"].startswith("bytes 0-99/")
    suffix = client.get(path, params={"token": token}, headers={"Range": "bytes=-10"})
    assert len(suffix.content) == 10
    assert (
        client.get(path, params={"token": token}, headers={"Range": "bytes=999999999-"}).status_code
        == 416
    )
    assert client.get(path, params={"token": "bad"}).status_code == 401
    # token bound to a different meeting is rejected
    other = upload_demo(client, owner)
    other_token = parse_qs(
        urlparse(
            client.get(f"/api/v1/meetings/{other['id']}", headers=auth(owner)).json()["audio_url"]
        ).query
    )["token"][0]
    assert client.get(path, params={"token": other_token}).status_code == 401


def test_exports(client: TestClient, owner: dict[str, str]) -> None:
    m = upload_demo(client, owner)
    md = client.get(f"/api/v1/meetings/{m['id']}/export?format=md", headers=auth(owner))
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    text = md.text
    assert "# Q3 Launch Planning" in text and "## Action items" in text and "## Transcript" in text
    assert 'filename="q3-launch-planning.md"' in md.headers["content-disposition"]
    no_tx = client.get(
        f"/api/v1/meetings/{m['id']}/export?format=md&transcript=false", headers=auth(owner)
    ).text
    assert "## Transcript" not in no_tx
    pdf = client.get(f"/api/v1/meetings/{m['id']}/export?format=pdf", headers=auth(owner))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and len(pdf.content) > 2000


def test_share_links(client: TestClient, owner: dict[str, str]) -> None:
    m = upload_demo(client, owner)
    share = client.post(f"/api/v1/meetings/{m['id']}/share", headers=auth(owner)).json()
    assert share["share_url"].endswith(share["share_token"])
    again = client.post(f"/api/v1/meetings/{m['id']}/share", headers=auth(owner)).json()
    assert again["share_token"] == share["share_token"]
    public = client.get(f"/api/v1/share/{share['share_token']}")
    assert public.status_code == 200
    body = public.json()
    assert body["title"] == "Q3 Launch Planning" and len(body["action_items"]) == 4
    assert "transcript" not in body
    assert (
        client.delete(f"/api/v1/meetings/{m['id']}/share", headers=auth(owner)).status_code == 204
    )
    assert client.get(f"/api/v1/share/{share['share_token']}").status_code == 404
    assert client.get("/api/v1/share/short").status_code == 404


def test_scheduled_meeting_attach_audio_and_reprocess(
    client: TestClient, owner: dict[str, str]
) -> None:
    with session_scope() as db:
        meeting = Meeting(
            workspace_id=owner["workspace_id"],
            title="Planned sync",
            source=MeetingSource.CALENDAR,
            status=MeetingStatus.SCHEDULED,
        )
        db.add(meeting)
        db.flush()
        mid = meeting.id
    assert client.post(f"/api/v1/meetings/{mid}/reprocess", headers=auth(owner)).status_code == 422
    assert client.post(f"/api/v1/meetings/{mid}/share", headers=auth(owner)).status_code == 422
    r = client.post(
        f"/api/v1/meetings/{mid}/audio",
        headers=auth(owner),
        files={"file": ("rec.wav", io.BytesIO(DEMO_WAV.read_bytes()), "audio/wav")},
    )
    assert r.status_code == 200
    detail = client.get(f"/api/v1/meetings/{mid}", headers=auth(owner)).json()
    assert detail["status"] == "completed" and detail["source"] == "calendar"
    rp = client.post(f"/api/v1/meetings/{mid}/reprocess", headers=auth(owner))
    assert rp.status_code == 202
    progress = client.get(f"/api/v1/meetings/{mid}/progress", headers=auth(owner)).json()
    assert progress["status"] == "completed" and progress["progress"] == 100
    items = client.get(
        f"/api/v1/workspaces/{owner['workspace_id']}/action-items?meeting_id={mid}",
        headers=auth(owner),
    ).json()
    assert len(items) == 4  # reprocessing replaces, not duplicates


def test_delete_meeting(client: TestClient, owner: dict[str, str]) -> None:
    m = upload_demo(client, owner)
    assert client.delete(f"/api/v1/meetings/{m['id']}", headers=auth(owner)).status_code == 204
    assert client.get(f"/api/v1/meetings/{m['id']}", headers=auth(owner)).status_code == 404
    assert (
        client.get(
            f"/api/v1/workspaces/{owner['workspace_id']}/action-items", headers=auth(owner)
        ).json()
        == []
    )
