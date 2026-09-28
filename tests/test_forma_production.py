"""Project #3 production engine: spec, doctrine rules, manual stills, budget, clip state machine, submit.

Fake fal transport only - no network, no cost. Nothing here can generate an image."""
import json
import shutil
from pathlib import Path

import httpx
import pytest

from app.forma.production import budget, rules, stills, submit
from app.forma.production.spec import load_spec
from app.forma.production.state import clip_state
from app.providers.video.fal import FalVideoProvider
from app.studio import attempt_status

EXAMPLE = Path(__file__).resolve().parent.parent / "docs" / "forma" / "production" / "example_project.json"
TEMPLATE = Path(__file__).resolve().parent.parent / "data" / "forma_project_3" / "project.json"


def png(w=768, h=1376, salt=b"") -> bytes:
    """A header-valid PNG (enough for sniffing and hashing)."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x02" + salt


def jpeg(w=768, h=1376) -> bytes:
    return (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            + b"\xff\xc0\x00\x11\x08" + h.to_bytes(2, "big") + w.to_bytes(2, "big") + b"\x03" + b"\x00" * 9 + b"\xff\xd9")


def webp(w=768, h=1376) -> bytes:
    return b"RIFF\x00\x00\x00\x00WEBPVP8X" + b"\x0a\x00\x00\x00" + b"\x00\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")


@pytest.fixture
def project(tmp_path):
    d = tmp_path / "forma_project_3"
    (d / "stills").mkdir(parents=True)
    shutil.copy(EXAMPLE, d / "project.json")
    (d / "manifest.json").write_text(json.dumps({"project": "forma_project_3"}))
    return load_spec(d / "project.json"), d / "manifest.json"


def _approve_all_stills(spec, manifest):
    for i, s in enumerate(spec.stills()):
        stills.upload(manifest, s.key, f"{s.key}.png", png(salt=bytes([i])))
        stills.approve(manifest, s.key, "looked at it")


# --- spec + rules --------------------------------------------------------------------------------

def test_template_is_empty_and_cannot_spend():
    spec = load_spec(TEMPLATE)
    assert spec.status == "template" and spec.concept is None and not spec.checkpoints and not spec.shots
    assert spec.budget_cap_usd == 0.0  # nothing can be spent until a person sets a cap


def test_example_derives_the_anchored_clip_chain_with_adaptive_counts(project):
    spec, _ = project
    assert rules.errors(spec) == []
    assert [(c.key, c.start_still, c.end_still) for c in spec.clips()][:5] == [
        ("s01_clip1", "cp01_still", "s01_mid1_still"), ("s01_clip2", "s01_mid1_still", "cp02_still"),
        ("s02_clip1", "cp02_still", "s02_mid1_still"), ("s02_clip2", "s02_mid1_still", "s02_mid2_still"),
        ("s02_clip3", "s02_mid2_still", "cp03_still")]
    assert {s.id: s.clip_count for s in spec.shots} == {"s01": 2, "s02": 3, "s03": 1, "s04": 0, "s05": 1}
    assert spec.dependents("cp02_still") == ["s01_clip2", "s02_clip1"]
    assert "Edit the previous approved still" in next(s for s in spec.stills() if s.key == "s02_mid1_still").brief


@pytest.mark.parametrize("mutate,rule", [
    (lambda r: r["checkpoints"][2]["built"].remove("concrete pads"), "no regression"),
    (lambda r: r["checkpoints"][1]["materials"].clear(), "material flow"),
    (lambda r: r["shots"][0]["beats"].pop(), "adaptive clip count"),
    (lambda r: r["shots"][2].update(complexity="complex"), "adaptive clip count"),
    (lambda r: r["shots"][0].update(camera_moves=True), "camera vs complexity"),
    (lambda r: r["shots"][0].update(proof=False), "model routing"),
    (lambda r: r["shots"][3].update(beats=[{"task": "x", "location": "y"}]), "static = still edit"),
    (lambda r: r["checkpoints"][1].update(camera="close"), "stable cameras"),
    (lambda r: r["shots"][2]["beats"][0].update(duration_seconds=3), "model limits"),  # Seedance 2.5 is 4-30 s
    (lambda r: r["shots"][0].update(model="alibaba/wan-3.0/image-to-video"), "model routing"),  # failed for labor
])
def test_rules_catch_doctrine_violations(tmp_path, mutate, rule):
    raw = json.loads(EXAMPLE.read_text())
    mutate(raw)
    path = tmp_path / "project.json"
    path.write_text(json.dumps(raw))
    assert rule in {p.rule for p in rules.errors(load_spec(path))}


# --- manual stills -------------------------------------------------------------------------------

@pytest.mark.parametrize("data,kind", [(png(), "png"), (jpeg(), "jpeg"), (webp(), "webp")])
def test_upload_places_the_still_under_its_canonical_name_without_approving(project, data, kind):
    spec, manifest = project
    out = stills.upload(manifest, "cp01_still", f"from chatgpt.{'jpg' if kind == 'jpeg' else kind}", data)
    assert out["state"] == "placed" and out["file_type"] == kind and (out["width"], out["height"]) == (768, 1376)
    assert Path(out["stored_as"]).name == f"cp01_still.{'jpg' if kind == 'jpeg' else kind}"
    assert json.loads(manifest.read_text())["still_uploads"]["cp01_still"]["sha256"] == out["sha256"]
    assert "cp01_still" not in json.loads(manifest.read_text())  # not approved


def test_upload_refuses_non_images_and_unconfirmed_replacement(project):
    _, manifest = project
    with pytest.raises(stills.StillError, match="Accepted formats"):
        stills.upload(manifest, "cp01_still", "notes.txt", png())
    with pytest.raises(stills.StillError, match="Not a JPEG, PNG or WebP"):
        stills.upload(manifest, "cp01_still", "fake.png", b"hello world, not an image at all.......")
    stills.upload(manifest, "cp01_still", "a.png", png())
    with pytest.raises(stills.StillError, match="Confirm replacement") as e:
        stills.upload(manifest, "cp01_still", "b.png", png(salt=b"b"))
    assert e.value.status == 409


def test_replacing_an_approved_still_marks_it_changed_and_its_clips_stale(project):
    spec, manifest = project
    stills.upload(manifest, "cp01_still", "a.png", png())
    stills.approve(manifest, "cp01_still", "matches the camera bible")
    assert stills.state(manifest, "cp01_still")["state"] == "approved"
    first_sha = stills.state(manifest, "cp01_still")["sha256"]
    data = json.loads(manifest.read_text())
    data["s01_clip1__attempt1"] = {"provider_job_id": "j", "start_still": "cp01_still", "start_frame_sha256": first_sha}
    manifest.write_text(json.dumps(data))
    out = stills.upload(manifest, "cp01_still", "b.jpg", jpeg(), replace=True)
    assert out["state"] == "changed" and out["replaced"]["previous_state"] == "approved"
    assert Path(out["replaced"]["archived_to"][0]).is_file()  # the old file is kept, never deleted
    info = stills.info(manifest, "cp01_still", label="x", dependents=spec.dependents("cp01_still"))
    assert info["used_by"] == [{"clip": "s01_clip1", "generated": True, "stale": True}]
    with pytest.raises(stills.StillError, match="must be approved"):
        stills.approved_file(manifest, "cp01_still")
    stills.approve(manifest, "cp01_still", "new version checked")
    assert stills.state(manifest, "cp01_still")["state"] == "approved"
    assert json.loads(manifest.read_text())["cp01_still__attempt1"]["approved_sha256"] == first_sha


# --- budget + state machine + submit ------------------------------------------------------------

class FakeFal:
    def __init__(self):
        self.calls, self.status = [], "IN_QUEUE"

    def __call__(self, request):
        url = str(request.url)
        self.calls.append(url)
        if url.endswith("/storage/upload/initiate"):
            return httpx.Response(200, json={"upload_url": "https://up.test/x", "file_url": f"https://f.test/{len(self.calls)}.png"})
        if url.startswith("https://up.test/"):
            return httpx.Response(200)
        if url.startswith("https://queue.fal.run/") and request.method == "POST":
            return httpx.Response(200, json={"request_id": "job-1", "status_url": "https://q.test/s", "response_url": "https://q.test/r"})
        if url == "https://q.test/s":
            return httpx.Response(200, json={"status": self.status})
        if url == "https://q.test/r":
            return httpx.Response(200, json={"video": {"url": "https://cdn.test/v.mp4"}})
        if url == "https://cdn.test/v.mp4":
            return httpx.Response(200, content=b"mp4")
        return httpx.Response(404)

    def submits(self):
        return sum(u.startswith("https://queue.fal.run/") for u in self.calls)


def _provider(spec, clip_key, fake):
    clip = spec.clip(clip_key)
    return FalVideoProvider(submit.model_config(submit.route_for(clip), clip), api_key="k",
                            client=httpx.Client(transport=httpx.MockTransport(fake)))


def test_clip_walks_the_state_machine_with_one_approval_per_job(project):
    spec, manifest = project
    key = "s01_clip1"
    state = lambda: clip_state(spec, manifest, json.loads(manifest.read_text()), spec.clip(key))["state"]  # noqa: E731
    assert state() == "blocked"
    _approve_all_stills(spec, manifest)
    assert state() == "ready"
    with pytest.raises(budget.BudgetError, match="per-clip ceiling"):
        budget.approve(manifest, spec, key, 5.0, "too much")
    budget.approve(manifest, spec, key, 0.30, "proof of Kling on pad setting")
    assert state() == "budget_approved"

    fake = FakeFal()
    with pytest.raises(submit.SubmitError, match="need STUDIO_EXECUTION_MODE=live"):
        submit.submit(spec, manifest, key, execution_mode="disabled", provider=_provider(spec, key, fake))
    entry = submit.submit(spec, manifest, key, execution_mode="live", provider=_provider(spec, key, fake))
    assert fake.submits() == 1 and entry["attempt"] == f"{key}__attempt1" and entry["estimated_cost_usd"] == 0.252
    assert entry["payload"]["generate_audio"] is False and entry["payload"]["end_image_url"]
    assert state() == "submitted"
    with pytest.raises(submit.SubmitError) as again:  # the approval is consumed: no second job
        submit.submit(spec, manifest, key, execution_mode="live", provider=_provider(spec, key, fake))
    assert fake.submits() == 1 and any("in flight" in p for p in again.value.problems)

    attempt_status.check_attempt(manifest, f"{key}__attempt1", provider=_provider(spec, key, fake), force=True)
    assert state() == "queued"
    fake.status = "COMPLETED"
    attempt_status.check_attempt(manifest, f"{key}__attempt1", provider=_provider(spec, key, fake), force=True)
    assert state() == "review"
    assert budget.spend(json.loads(manifest.read_text()), spec)["spent_usd"] == 0.252 + 0.0

    submit.review(spec, manifest, key, f"{key}__attempt1", "accept", "pads look real")
    assert state() == "accepted"
    assert budget.spend(json.loads(manifest.read_text()), spec)["spent_usd"] == 0.252  # not double counted

    stills.upload(manifest, "cp01_still", "new.png", png(salt=b"new"), replace=True)
    assert state() == "stale"


def test_a_rejected_attempt_needs_a_new_approval_and_is_never_retried(project):
    spec, manifest = project
    key = "s05_clip1"  # environmental -> Wan 3.0 (proven_environmental)
    _approve_all_stills(spec, manifest)
    budget.approve(manifest, spec, key, 0.20, "reveal")
    fake = FakeFal()
    fake.status = "COMPLETED"
    submit.submit(spec, manifest, key, execution_mode="live", provider=_provider(spec, key, fake))
    attempt_status.check_attempt(manifest, f"{key}__attempt1", provider=_provider(spec, key, fake), force=True)
    submit.review(spec, manifest, key, f"{key}__attempt1", "reject", "camera drifted")
    plan = submit.plan(spec, manifest, key)
    assert plan["state"] == "ready" and "new spend approval" in plan["reasons"][0]
    assert plan["route"]["model"] == "alibaba/wan-3.0/image-to-video" and plan["estimate_usd"] == 0.15
    assert fake.submits() == 1


def test_the_project_cap_counts_jobs_in_flight(project):
    spec, manifest = project
    spec.budget_cap_usd = 0.30
    _approve_all_stills(spec, manifest)
    fake = FakeFal()
    budget.approve(manifest, spec, "s01_clip1", 0.30, "a")
    submit.submit(spec, manifest, "s01_clip1", execution_mode="live", provider=_provider(spec, "s01_clip1", fake))
    budget.approve(manifest, spec, "s01_clip2", 0.30, "b")
    with pytest.raises(submit.SubmitError) as e:
        submit.submit(spec, manifest, "s01_clip2", execution_mode="live", provider=_provider(spec, "s01_clip2", fake))
    assert any("in flight" in p and "would exceed" in p for p in e.value.problems) and fake.submits() == 1


# --- studio -------------------------------------------------------------------------------------

def test_studio_upload_and_approve_endpoints_are_local(client, tmp_path, monkeypatch, project):
    from app.config import settings
    from app.studio.importers.manifest_importer import import_all

    spec, manifest = project
    monkeypatch.setattr(type(settings), "studio_data_path", property(lambda self: tmp_path))
    from app.db import SessionLocal
    with SessionLocal() as db:
        results = import_all(db, tmp_path, slugs=["forma_project_3"])
    assert results[0].found and results[0].stages_total == len(spec.stills()) + len(spec.clips())

    def refuse_network(*a, **k):
        raise AssertionError("no provider call allowed")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse_network)  # the real network, not TestClient

    url = "/studio/projects/forma_project_3/stills/s01_mid1_still"
    r = client.post(f"{url}/upload?filename=A.png", content=png())
    assert r.status_code == 200 and r.json()["state"] == "placed"
    assert client.post(f"{url}/upload?filename=B.png", content=png(salt=b"b")).status_code == 409
    assert client.post(f"{url}/upload?filename=B.png&replace=true", content=png(salt=b"b")).status_code == 200
    assert client.post(f"{url}/approve", json={"note": "clearing matches"}).json()["state"] == "approved"

    snap = client.get("/studio/snapshot?project=forma_project_3").json()
    assert snap["project"]["spec_driven"] and not snap["project"]["frozen"]
    stage = next(s for s in snap["stages"] if s["key"] == "s01_mid1_still")
    ms = stage["manual_still"]
    assert ms["state"] == "approved" and ms["file_type"] == "png" and (ms["width"], ms["height"]) == (768, 1376)
    assert [u["clip"] for u in ms["used_by"]] == ["s01_clip1", "s01_clip2"] and stage["room_id"] == "continuity_office"
    clip = next(s for s in snap["stages"] if s["key"] == "s01_clip1")
    assert clip["clip_plan"]["state"] == "blocked" and clip["clip_plan"]["route"]["status"] == "candidate_unproven"


def test_the_train_car_is_frozen_but_its_stills_are_still_manual_and_uploadable():
    from app.studio import manual_stills
    from app.studio.importers.stage_maps import PROJECTS_BY_SLUG
    from scripts import run_train_car_video_2_plan as plan

    assert PROJECTS_BY_SLUG["train_car_video_2"].frozen and plan.FROZEN
    cat = manual_stills.catalog("train_car_video_2", Path("data/train_car_video_2/manifest.json"))
    assert {"cp03a_still", "cp03b_still", "cp02_still"} <= set(cat)
    assert "clip03__attempt6" in cat["cp03a_still"]["used_by"]
