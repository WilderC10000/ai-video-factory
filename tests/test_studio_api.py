"""FORMA Virtual Studio - /studio/* endpoints over synthetic imported data."""
from urllib.parse import quote

from app.studio.importers.manifest_importer import import_all
from tests.test_studio_importer import data_dir  # noqa: F401  (fixture)


def test_empty_snapshot_before_any_import(client):
    body = client.get("/studio/snapshot").json()
    assert body["projects"] == [] and body["project"] is None
    assert body["execution"]["mode"] == "disabled" and body["execution"]["launch_enabled"] is False


def test_snapshot_derives_agent_status_from_real_state(client, db_session, data_dir):  # noqa: F811
    import_all(db_session, data_dir)
    body = client.get("/studio/snapshot").json()

    assert body["project"]["slug"] == "alpine_video_2" and body["project"]["is_demo"] is False
    assert len(body["rooms"]) == 11 and len(body["stages"]) == 16
    agents = {r["id"]: r["agent"] for r in body["rooms"]}
    assert agents["screening_room"]["status"] == "waiting_for_approval"
    assert agents["screening_room"]["requires_human_review"] is True
    assert agents["render_bay"]["status"] == "waiting_for_approval"
    assert agents["render_bay"]["requires_human_review"] is False  # normal waiting, not waiting on you
    assert agents["continuity_office"]["status"] == "complete"
    assert agents["sound_booth"]["status"] == "idle" and "No data source" in agents["sound_booth"]["status_reason"]
    assert body["budget"]["spent_usd"] == 3.6

    cliff = client.get("/studio/snapshot?project=cliffside_video_1").json()
    assert cliff["project"]["slug"] == "cliffside_video_1"
    cliff_agents = {r["id"]: r["agent"] for r in cliff["rooms"]}
    # The final cut has no recorded approval, so the room that produced it asks for review.
    assert cliff_agents["edit_suite"]["status"] == "waiting_for_approval"
    assert cliff_agents["edit_suite"]["requires_human_review"] is True


def test_media_is_confined_to_the_data_directory(client):
    assert client.get(f"/studio/media?path={quote('C:/Windows/win.ini')}").status_code == 403
    assert client.get("/studio/media?path=" + quote("data/../.env")).status_code == 403
    assert client.get("/studio/media?path=" + quote("data/alpine_video_2/manifest.json")).status_code == 403


def test_activate_switches_the_active_project(client, db_session, data_dir):  # noqa: F811
    import_all(db_session, data_dir)
    assert client.post("/studio/projects/cliffside_video_1/activate").status_code == 200
    assert client.get("/studio/snapshot").json()["project"]["slug"] == "cliffside_video_1"
    assert client.post("/studio/projects/nope/activate").status_code == 404
