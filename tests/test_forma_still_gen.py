"""Project #3 generated stills: CP01 text-to-image, every later still an edit of the previous approved still,
one confirmed call per still, nothing approved or chained automatically.

Fake fal transport / mock provider only - no network, no cost."""
import json
import shutil
from pathlib import Path

import httpx
import pytest

from app.forma.production import budget, rules, still_gen, stills
from app.forma.production.spec import load_spec
from app.providers.image.fal import NANO_BANANA_EDIT, NANO_BANANA_GENERATE, FalImageProvider

EXAMPLE = Path(__file__).resolve().parent.parent / "docs" / "forma" / "production" / "example_project.json"
TEMPLATE = Path(__file__).resolve().parent.parent / "data" / "forma_project_3" / "project.json"


def png(w=768, h=1344, salt=b"") -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x02" + salt


class FakeFalImage:
    """fal's sync image endpoints: upload (initiate + PUT), generate/edit, download."""

    def __init__(self, fail_status: int | None = None):
        self.calls: list[tuple[str, str, bytes]] = []
        self.fail_status = fail_status
        self.n = 0

    def __call__(self, request):
        url, body = str(request.url), request.read()
        self.calls.append((request.method, url, body))
        if url.endswith("/storage/upload/initiate"):
            return httpx.Response(200, json={"upload_url": "https://up.test/x", "file_url": "https://f.test/src.png"})
        if url.startswith("https://up.test/"):
            return httpx.Response(200)
        if url.startswith("https://fal.run/"):
            if self.fail_status:
                return httpx.Response(self.fail_status, text="rejected")
            self.n += 1
            return httpx.Response(200, json={"images": [{"url": f"https://cdn.test/{self.n}.png"}]})
        if url.startswith("https://cdn.test/"):
            return httpx.Response(200, content=png(salt=url.encode()))
        return httpx.Response(404)

    def model_posts(self):
        return [(u, json.loads(b)) for m, u, b in self.calls if u.startswith("https://fal.run/")]

    def uploads(self):
        return [b for m, u, b in self.calls if u.startswith("https://up.test/")]


def fal(cfg, fake):
    return FalImageProvider(cfg, api_key="k", client=httpx.Client(transport=httpx.MockTransport(fake)))


@pytest.fixture
def project(tmp_path):
    d = tmp_path / "forma_project_3"
    (d / "stills").mkdir(parents=True)
    shutil.copy(EXAMPLE, d / "project.json")
    (d / "manifest.json").write_text(json.dumps({"project": "forma_project_3"}))
    return load_spec(d / "project.json"), d / "manifest.json"


def test_the_first_still_is_text_to_image_and_every_later_still_edits_the_previous_one(project):
    spec, manifest = project
    keys = [s.key for s in spec.stills()]
    assert spec.stills_config.source == "generate" and spec.edit_source(keys[0]) is None
    assert all(spec.edit_source(k) == keys[i] for i, k in enumerate(keys[1:]))
    first = still_gen.plan(spec, manifest, "cp01_still")
    assert (first["mode"], first["model"], first["estimate_usd"], first["source"]) == \
        ("generate", "fal-ai/nano-banana", 0.0398, None)
    assert first["problems"] == []
    mid = still_gen.plan(spec, manifest, "s01_mid1_still")
    assert (mid["mode"], mid["model"], mid["source"]["key"]) == ("edit", "fal-ai/nano-banana/edit", "cp01_still")
    assert any("approve it first" in p for p in mid["problems"])


def test_one_confirmed_call_places_the_still_unapproved_and_records_its_cost(project):
    spec, manifest = project
    fake = FakeFalImage()
    with pytest.raises(still_gen.StillGenError, match="Confirm"):
        still_gen.generate(spec, manifest, "cp01_still", execution_mode="live", max_usd=0.05, confirmed=False)
    with pytest.raises(still_gen.StillGenError, match="disabled"):
        still_gen.generate(spec, manifest, "cp01_still", execution_mode="disabled", max_usd=0.05, confirmed=True)
    with pytest.raises(still_gen.StillGenError) as e:
        still_gen.generate(spec, manifest, "cp01_still", execution_mode="live", max_usd=0.01, confirmed=True,
                           provider=fal(NANO_BANANA_GENERATE, fake))
    assert any("above the approved" in p for p in e.value.problems) and fake.calls == []

    out = still_gen.generate(spec, manifest, "cp01_still", execution_mode="live", max_usd=0.05, confirmed=True,
                             provider=fal(NANO_BANANA_GENERATE, fake))
    [(url, payload)] = fake.model_posts()
    assert url == "https://fal.run/fal-ai/nano-banana" and payload["aspect_ratio"] == "9:16"
    assert "resolution" not in payload and payload["num_images"] == 1 and payload["prompt"].startswith("CP01")
    assert out["state"] == "placed" and out["actual_cost_usd"] == 0.0398 and out["status"] == "complete"
    m = json.loads(manifest.read_text())
    assert budget.spend(m, spec)["spent_usd"] == 0.0398
    assert stills.info(manifest, "cp01_still", label="x", dependents=[])["origin"] == "generated"
    assert "cp01_still" not in m or not m["cp01_still"].get("approved_sha256")  # never auto-approved

    # Nothing chained: the next still was not generated, and cannot be until cp01 is approved.
    assert stills.state(manifest, "s01_mid1_still")["state"] == "missing"
    with pytest.raises(still_gen.StillGenError) as e:
        still_gen.generate(spec, manifest, "s01_mid1_still", execution_mode="live", max_usd=0.05, confirmed=True,
                           provider=fal(NANO_BANANA_EDIT, fake))
    assert any("approve it first" in p for p in e.value.problems) and len(fake.model_posts()) == 1


def test_a_later_still_is_an_edit_of_the_exact_approved_pixels(project):
    spec, manifest = project
    fake = FakeFalImage()
    still_gen.generate(spec, manifest, "cp01_still", execution_mode="live", max_usd=0.05, confirmed=True,
                       provider=fal(NANO_BANANA_GENERATE, fake))
    stills.approve(manifest, "cp01_still", "pipe, builder, camera ok")
    approved_path, approved_sha = stills.approved_file(manifest, "cp01_still")

    out = still_gen.generate(spec, manifest, "s01_mid1_still", execution_mode="live", max_usd=0.05, confirmed=True,
                             provider=fal(NANO_BANANA_EDIT, fake))
    url, payload = fake.model_posts()[-1]
    assert url == "https://fal.run/fal-ai/nano-banana/edit" and payload["image_urls"] == ["https://f.test/src.png"]
    assert payload["aspect_ratio"] == "auto" and payload["output_format"] == "png"
    assert fake.uploads()[-1] == approved_path.read_bytes()  # the approved file itself went to fal
    assert out["source_still"] == "cp01_still" and out["source_sha256"] == approved_sha
    assert "The attached image is authoritative" in payload["prompt"] and "lighting" in payload["prompt"]
    assert out["state"] == "placed"


def test_regenerating_needs_replace_and_marks_the_next_still_as_made_from_old_pixels(project):
    spec, manifest = project
    fake = FakeFalImage()
    gen = lambda key, cfg, **kw: still_gen.generate(spec, manifest, key, execution_mode="live", max_usd=0.05,
                                                    confirmed=True, provider=fal(cfg, fake), **kw)
    gen("cp01_still", NANO_BANANA_GENERATE)
    stills.approve(manifest, "cp01_still", "ok")
    gen("s01_mid1_still", NANO_BANANA_EDIT)
    with pytest.raises(still_gen.StillGenError) as e:
        gen("cp01_still", NANO_BANANA_GENERATE)
    assert any("Confirm replacement" in p for p in e.value.problems)
    gen("cp01_still", NANO_BANANA_GENERATE, replace=True)
    assert stills.state(manifest, "cp01_still")["state"] == "changed"
    stills.approve(manifest, "cp01_still", "new version ok")
    assert still_gen.plan(spec, manifest, "s01_mid1_still")["stale_source"] is True
    assert budget.spend(json.loads(manifest.read_text()), spec)["spent_usd"] == round(3 * 0.0398, 4)


def test_a_refused_request_is_not_charged_and_not_retried(project):
    spec, manifest = project
    fake = FakeFalImage(fail_status=422)
    with pytest.raises(still_gen.StillGenError, match="not charged"):
        still_gen.generate(spec, manifest, "cp01_still", execution_mode="live", max_usd=0.05, confirmed=True,
                           provider=fal(NANO_BANANA_GENERATE, fake))
    m = json.loads(manifest.read_text())
    assert m["cp01_still__gen1"]["status"] == "failed" and m["cp01_still__gen1"]["actual_cost_usd"] == 0.0
    assert len(fake.model_posts()) == 1 and stills.state(manifest, "cp01_still")["state"] == "missing"


def test_the_project_cap_and_manual_source_block_generation(project, tmp_path):
    spec, manifest = project
    raw = json.loads(EXAMPLE.read_text())
    raw["budget"]["cap_usd"] = 0.0
    path = manifest.parent / "project.json"
    path.write_text(json.dumps(raw))
    assert any("would exceed" in p for p in still_gen.plan(load_spec(path), manifest, "cp01_still")["problems"])
    raw["stills"] = {"source": "manual"}
    path.write_text(json.dumps(raw))
    assert any("manual stills" in p for p in still_gen.plan(load_spec(path), manifest, "cp01_still")["problems"])


def test_mock_mode_generates_for_free_without_a_network_call(project, monkeypatch):
    spec, manifest = project
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *a, **k: pytest.fail("network call"))
    still_gen.generate(spec, manifest, "cp01_still", execution_mode="mock", max_usd=0.05, confirmed=True)
    stills.approve(manifest, "cp01_still", "ok")
    out = still_gen.generate(spec, manifest, "s01_mid1_still", execution_mode="mock", max_usd=0.05, confirmed=True)
    assert out["state"] == "placed" and out["actual_cost_usd"] == 0.0
    assert budget.spend(json.loads(manifest.read_text()), spec)["spent_usd"] == 0.0


def test_studio_generate_endpoint_is_gated_and_never_approves(client, tmp_path, monkeypatch, project):
    from app.config import settings
    from app.db import SessionLocal
    from app.studio.importers.manifest_importer import import_all

    spec, manifest = project
    monkeypatch.setattr(type(settings), "studio_data_path", property(lambda self: tmp_path))
    with SessionLocal() as db:
        import_all(db, tmp_path, slugs=["forma_project_3"])
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *a, **k: pytest.fail("network call"))
    url = "/studio/projects/forma_project_3/stills/cp01_still"

    monkeypatch.setattr(settings, "studio_execution_mode", "disabled")
    r = client.post(f"{url}/generate", json={"max_usd": 0.05, "confirmed": True})
    assert r.status_code == 409 and stills.state(manifest, "cp01_still")["state"] == "missing"

    monkeypatch.setattr(settings, "studio_execution_mode", "mock")
    assert client.post(f"{url}/generate", json={"max_usd": 0.05}).status_code == 400  # not confirmed
    r = client.post(f"{url}/generate", json={"max_usd": 0.05, "confirmed": True})
    assert r.status_code == 200 and r.json()["state"] == "placed"

    snap = client.get("/studio/snapshot?project=forma_project_3").json()
    ms = next(s for s in snap["stages"] if s["key"] == "cp01_still")["manual_still"]
    assert ms["state"] == "placed" and ms["origin"] == "generated" and ms["generation"]["mode"] == "generate"
    nxt = next(s for s in snap["stages"] if s["key"] == "s01_mid1_still")["manual_still"]["generation"]
    assert nxt["mode"] == "edit" and nxt["source"]["key"] == "cp01_still" and nxt["problems"]
    # Upload stays available as an override.
    r = client.post(f"/studio/projects/forma_project_3/stills/cp01_still/upload?filename=A.png&replace=true",
                    content=png())
    assert r.status_code == 200 and stills.info(manifest, "cp01_still", label="x", dependents=[])["origin"] == "uploaded"


def test_project_3_template_generates_stills_by_default_with_the_cheap_tier():
    spec = load_spec(TEMPLATE)
    sc = spec.stills_config
    assert (sc.source, sc.generate_model, sc.edit_model) == ("generate", "fal-ai/nano-banana", "fal-ai/nano-banana/edit")
    assert rules.errors(spec) == []
    assert spec.edit_source("cp02_still") == "s01_mid1_still" and spec.edit_source("cp04_still") == "cp03_still"
    assert "The attached image is authoritative" in next(s.brief for s in spec.stills() if s.key == "cp10_still")


def test_a_proof_allowlist_blocks_every_other_still(project):
    spec, manifest = project
    raw = json.loads(EXAMPLE.read_text())
    raw["stills"] = {"proof_stills": ["cp01_still", "s01_mid1_still"]}
    path = manifest.parent / "project.json"
    path.write_text(json.dumps(raw))
    spec = load_spec(path)
    assert still_gen.plan(spec, manifest, "cp01_still")["problems"] == []
    assert any("Proof in progress" in p for p in still_gen.plan(spec, manifest, "cp02_still")["problems"])
    assert not any("Proof in progress" in p for p in still_gen.plan(spec, manifest, "s01_mid1_still")["problems"])


def test_project_3_still_proof_runs_through_s02_mid1_under_a_one_dollar_cap():
    spec = load_spec(TEMPLATE)
    assert spec.budget_cap_usd == 1.0
    assert spec.stills_config.proof_stills == ("cp01_still", "s01_mid1_still", "cp02_still", "s02_mid1_still")
    assert spec.stills_config.model_for("s02_mid1_still", False) == "fal-ai/nano-banana-2/edit"
    assert spec.stills_config.model_for("cp03_still", False) == "fal-ai/nano-banana/edit"
    s02 = next(s for s in spec.shots if s.id == "s02")
    assert s02.clip_count == 3 and not s02.hold and spec.stills_config.model_for("s02_mid2_still", False).endswith("2/edit")


# --- still doctrine: explicit end states, continuity checkpoints --------------------------------

def test_a_removal_end_state_must_say_what_is_gone_and_where_it_went(tmp_path):
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    raw["shots"][0]["beats"][0]["after"] = "the builder has cut the branch"
    path = tmp_path / "project.json"
    path.write_text(json.dumps(raw))
    hits = [p for p in rules.check(load_spec(path)) if p.rule == "explicit end state"]
    assert [p.where for p in hits] == ["s01 beat 1"] and "where the removed material ends up" in hits[0].message
    assert not [p for p in rules.check(load_spec(TEMPLATE)) if p.rule == "explicit end state"]


def test_every_fifth_chained_edit_blocks_the_chain_until_a_continuity_check_passes(project):
    from app.forma.production import continuity

    spec, manifest = project
    keys = [s.key for s in spec.stills()]
    assert continuity.chain_position(spec, "cp01_still") == ("cp01_still", 0)
    fifth = keys[5]
    assert continuity.chain_position(spec, fifth) == ("cp01_still", 5) and continuity.due(spec, fifth)
    for key in keys[:6]:
        still_gen.generate(spec, manifest, key, execution_mode="mock", max_usd=0.05, confirmed=True)
        stills.approve(manifest, key, "ok")
    nxt = keys[6]
    assert any("Continuity checkpoint" in p for p in still_gen.plan(spec, manifest, nxt)["problems"])
    with pytest.raises(continuity.ContinuityError, match="all of"):
        continuity.record(spec, manifest, fifth, "pass", "compared", {"geometry": True})
    continuity.record(spec, manifest, fifth, "fail", "builder face changed", {})
    assert any("FAILED" in p for p in still_gen.plan(spec, manifest, nxt)["problems"])
    continuity.record(spec, manifest, fifth, "pass", "pipe, camera, builder, forest hold",
                      {d: True for d in continuity.DIMENSIONS})
    assert still_gen.plan(spec, manifest, nxt)["problems"] == []
    # A different (replaced) fifth still needs a new check. (A mock edit returns its source unchanged, so upload.)
    stills.upload(manifest, fifth, "other.png", png(salt=b"other"), replace=True)
    stills.approve(manifest, fifth, "new version")
    assert any("Continuity checkpoint" in p for p in still_gen.plan(spec, manifest, nxt)["problems"])


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_drift_metrics_find_the_frame_offset_between_cp01_and_s01_mid1():
    from app.forma.production import continuity

    d = TEMPLATE.parent / "stills"
    m = continuity.measure(d / "cp01_still.png", d / "s01_mid1_still.png")
    assert abs(m["offset_px"][0]) <= 12 and m["offset_pct"] < continuity.FLAG_SHIFT_PCT
    assert m["band_psnr_aligned_db"] > m["band_psnr_db"] - 0.01 and m["flags"] == []


def test_a_per_still_override_uses_another_tier_for_that_still_only(project):
    from app.providers.image.fal import NANO_BANANA_2_EDIT

    spec, manifest = project
    raw = json.loads(EXAMPLE.read_text())
    raw["stills"] = {"model_overrides": {"cp02_still": "fal-ai/nano-banana-2/edit"}}
    path = manifest.parent / "project.json"
    path.write_text(json.dumps(raw))
    spec = load_spec(path)
    assert rules.errors(spec) == []
    assert still_gen.plan(spec, manifest, "s01_mid1_still")["model"] == "fal-ai/nano-banana/edit"
    p = still_gen.plan(spec, manifest, "cp02_still")
    assert (p["model"], p["estimate_usd"], p["model_override"]) == ("fal-ai/nano-banana-2/edit", 0.08, True)
    fake = FakeFalImage()
    for key, cfg in (("cp01_still", NANO_BANANA_GENERATE), ("s01_mid1_still", NANO_BANANA_EDIT)):
        still_gen.generate(spec, manifest, key, execution_mode="live", max_usd=0.1, confirmed=True, provider=fal(cfg, fake))
        stills.approve(manifest, key, "ok")
    out = still_gen.generate(spec, manifest, "cp02_still", execution_mode="live", max_usd=0.1, confirmed=True,
                             provider=fal(NANO_BANANA_2_EDIT, fake))
    url, payload = fake.model_posts()[-1]
    assert url == "https://fal.run/fal-ai/nano-banana-2/edit" and payload["resolution"] == "1K"
    assert "resolution" not in fake.model_posts()[1][1]  # the cheap edit endpoint has no resolution field
    assert out["actual_cost_usd"] == 0.08 and out["model"] == "fal-ai/nano-banana-2/edit"
    raw["stills"] = {"model_overrides": {"cp02_still": "fal-ai/nano-banana-2"}}
    path.write_text(json.dumps(raw))
    assert any("edit endpoint" in p.message for p in rules.errors(load_spec(path)))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_stills_are_scaled_to_the_project_frame_size_and_a_normalized_approval_carries_over(project):
    from app.forma.production import submit

    spec, manifest = project
    raw = json.loads(EXAMPLE.read_text())
    path = manifest.parent / "project.json"
    path.write_text(json.dumps(raw))
    fixture = Path("app/providers/image/fixtures/mock_reference.jpg").read_bytes()  # a real 576x1024 JPEG
    # No frame size yet: a clip whose stills differ in size is blocked before any spend.
    stills.upload(manifest, "cp01_still", "a.jpg", fixture)
    stills.approve(manifest, "cp01_still", "ok")
    stills.upload(manifest, "s01_mid1_still", "b.png", png(768, 1344, b"x"))
    stills.approve(manifest, "s01_mid1_still", "ok")
    p = submit.plan(spec, manifest, "s01_clip1")
    assert p["state"] == "blocked" and "differ in size" in p["reasons"][0]
    # With a frame size, normalizing scales the approved file and keeps it approved.
    raw["stills"] = {"frame_size": [768, 1344]}
    path.write_text(json.dumps(raw))
    spec = load_spec(path)
    out = still_gen.normalize_approved(spec, manifest, "cp01_still")
    assert out["normalized"] and out["from"] == [576, 1024]
    info = stills.info(manifest, "cp01_still", label="x", dependents=[])
    assert info["state"] == "approved" and (info["width"], info["height"]) == (768, 1344)
    assert "normalization only" in info["approval_note"]
    assert still_gen.normalize_approved(spec, manifest, "cp01_still")["normalized"] is False
    # A generated still that comes back at another size is scaled before it is placed.
    stills.upload(manifest, "cp01_still", "a.jpg", fixture, replace=True)
    stills.approve(manifest, "cp01_still", "ok")
    out = still_gen.generate(spec, manifest, "s01_mid1_still", execution_mode="mock", max_usd=0.05, confirmed=True,
                             replace=True)
    assert out["normalized_from"] == [576, 1024] and (out["width"], out["height"]) == (768, 1344)


def test_a_shot_on_hold_blocks_its_clips_but_not_its_stills(project):
    from app.forma.production import submit

    spec, manifest = project
    raw = json.loads(EXAMPLE.read_text())
    raw["shots"][0]["hold"] = "check the start pose"
    path = manifest.parent / "project.json"
    path.write_text(json.dumps(raw))
    spec = load_spec(path)
    for i, s in enumerate(spec.stills()):
        stills.upload(manifest, s.key, f"{s.key}.png", png(salt=bytes([i])))
        stills.approve(manifest, s.key, "ok")
    p = submit.plan(spec, manifest, "s01_clip1")
    assert p["state"] == "blocked" and "on hold: check the start pose" in p["reasons"][0]
    assert "on hold" not in " ".join(submit.plan(spec, manifest, "s02_clip1")["reasons"])
    assert any(x.rule == "on hold" for x in rules.check(spec))


def test_archiving_a_failed_still_frees_its_key_but_never_an_approved_one(project):
    spec, manifest = project
    stills.upload(manifest, "cp01_still", "a.png", png())
    out = stills.archive(manifest, "cp01_still", "failed attempt kept as R&D")
    assert out["state"] == "missing" and Path(out["archived_to"][0]).is_file()
    assert stills.state(manifest, "cp01_still")["state"] == "missing"
    stills.upload(manifest, "cp01_still", "b.png", png(salt=b"b"))
    stills.approve(manifest, "cp01_still", "ok")
    with pytest.raises(stills.StillError, match="approved"):
        stills.archive(manifest, "cp01_still", "x")
