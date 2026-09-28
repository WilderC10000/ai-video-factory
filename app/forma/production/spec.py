"""The Project #3 production spec: checkpoint-first planning in one project.json.

A project is a chain of CHECKPOINTS (visible construction states, each an approved manual still) joined by
SHOTS (the work between two consecutive checkpoints). A shot's complexity decides its clip count (doctrine
production lesson 11): simple 1, medium 2, complex up to 3, static 0 (the end checkpoint still is the
phase-completion edit - no video). A shot with N clips gets N-1 intermediate stills, so every clip runs
first/last frame between two approved stills and clips are joined by hard cuts in the edit:

    cp02_still --s02_clip1--> s02_mid1_still --s02_clip2--> s02_mid2_still --s02_clip3--> cp03_still

Keys are deterministic from the spec, so the manifest, the stills folder and the studio agree on names.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.forma.doctrine import SHOT_CLASSES

COMPLEXITY_CLIPS = {"simple": 1, "medium": 2, "complex": 3, "static": 0}
STILL_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


class SpecError(Exception):
    pass


@dataclass(frozen=True)
class Checkpoint:
    id: str  # "cp01"
    title: str
    state: str  # what is visibly true in this still
    camera: str  # key of ProjectSpec.cameras
    built: tuple[str, ...] = ()  # every construction element present (cumulative)
    materials: dict[str, str] = field(default_factory=dict)  # element -> where its material visibly comes from
    tools_in_view: tuple[str, ...] = ()

    @property
    def still_key(self) -> str:
        return f"{self.id}_still"


@dataclass(frozen=True)
class Beat:
    task: str  # one local physical task
    location: str  # where in the frame / work area
    duration_seconds: int = 3


@dataclass(frozen=True)
class Shot:
    id: str  # "s02"
    from_cp: str
    to_cp: str
    title: str
    complexity: str  # simple | medium | complex | static
    shot_class: str  # doctrine.SHOT_CLASSES key
    beats: tuple[Beat, ...] = ()
    camera_moves: bool = False
    proof: bool = False  # the first clip of an unproven route: allowed only as a proof
    model: str | None = None  # explicit fal model (must be an allowed route); None = routing decides

    @property
    def clip_count(self) -> int:
        return len(self.beats) if self.complexity != "static" else 0

    def clip_keys(self) -> list[str]:
        return [f"{self.id}_clip{n}" for n in range(1, self.clip_count + 1)]

    def mid_still_keys(self) -> list[str]:
        return [f"{self.id}_mid{n}_still" for n in range(1, self.clip_count)]


@dataclass(frozen=True)
class Clip:
    key: str
    shot: Shot
    n: int
    beat: Beat
    start_still: str
    end_still: str


@dataclass(frozen=True)
class Still:
    key: str
    label: str
    kind: str  # "checkpoint" | "intermediate"
    brief: str
    checkpoint: str | None = None
    shot: str | None = None


@dataclass
class ProjectSpec:
    slug: str
    name: str
    status: str  # template | planning | production | frozen
    budget_cap_usd: float
    per_clip_max_usd: float
    concept: dict | None = None
    bibles: dict[str, str] = field(default_factory=dict)  # location / structure / builder / materials
    cameras: dict[str, str] = field(default_factory=dict)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    shots: list[Shot] = field(default_factory=list)

    # --- derived -------------------------------------------------------------------------------------
    def checkpoint(self, cp_id: str) -> Checkpoint:
        for cp in self.checkpoints:
            if cp.id == cp_id:
                return cp
        raise SpecError(f"Unknown checkpoint {cp_id!r}")

    def clips(self) -> list[Clip]:
        out = []
        for shot in self.shots:
            chain = [self.checkpoint(shot.from_cp).still_key, *shot.mid_still_keys(),
                     self.checkpoint(shot.to_cp).still_key]
            for n, (key, beat) in enumerate(zip(shot.clip_keys(), shot.beats), 1):
                out.append(Clip(key, shot, n, beat, chain[n - 1], chain[n]))
        return out

    def clip(self, key: str) -> Clip:
        for clip in self.clips():
            if clip.key == key:
                return clip
        raise SpecError(f"Unknown clip {key!r}")

    def stills(self) -> list[Still]:
        """Every manual still, in production order (a shot's intermediates before its end checkpoint)."""
        out: list[Still] = []
        seen = set()
        shots_into = {s.to_cp: s for s in self.shots}
        for cp in self.checkpoints:
            shot = shots_into.get(cp.id)
            if shot is not None:
                for n, key in enumerate(shot.mid_still_keys(), 1):
                    out.append(Still(key, f"{shot.id} intermediate {n}/{shot.clip_count - 1} - {shot.title}",
                                     "intermediate", self._mid_brief(shot, n), shot=shot.id))
            if cp.still_key not in seen:
                out.append(Still(cp.still_key, f"{cp.id.upper()} - {cp.title}", "checkpoint",
                                 self._cp_brief(cp), checkpoint=cp.id))
                seen.add(cp.still_key)
        return out

    def still_keys(self) -> set[str]:
        return {s.key for s in self.stills()}

    def dependents(self, still_key: str) -> list[str]:
        """Clips that start or end on this still."""
        return [c.key for c in self.clips() if still_key in (c.start_still, c.end_still)]

    # --- ChatGPT briefs ------------------------------------------------------------------------------
    def _lock(self, camera: str) -> str:
        return (f"Camera: {self.cameras.get(camera, camera)} - identical framing to the previous approved still. "
                f"Location: {self.bibles.get('location', '')} Builder: {self.bibles.get('builder', '')} "
                f"Structure: {self.bibles.get('structure', '')} Keep every pixel of the scene identical except the "
                "construction progress, the builder's position, tools and materials. Realistic documentary "
                "photograph, not illustration. Nothing already built may disappear or regress; add nothing that "
                "is not described.")

    def _cp_brief(self, cp: Checkpoint) -> str:
        new = [e for e in cp.built if e not in self._previous_built(cp)]
        materials = "; ".join(f"{e}: from {cp.materials[e]}" for e in new if e in cp.materials)
        return (f"{cp.id.upper()} - {cp.title}. Visible state: {cp.state} Built so far: "
                f"{', '.join(cp.built) or 'nothing yet'}. {('Material sources in view: ' + materials + '. ') if materials else ''}"
                f"Tools in view: {', '.join(cp.tools_in_view) or 'none'}. {self._lock(cp.camera)}")

    def _mid_brief(self, shot: Shot, n: int) -> str:
        cp_from, cp_to = self.checkpoint(shot.from_cp), self.checkpoint(shot.to_cp)
        done = shot.beats[n - 1]
        nxt = shot.beats[n]
        return (f"Intermediate still {n} of {shot.clip_count - 1} for shot {shot.id} ({shot.title}), between "
                f"{cp_from.id.upper()} and {cp_to.id.upper()}. Edit the previous approved still. Progress: the work "
                f"of beat {n} is done ({done.task}, at {done.location}); the builder is now positioned for beat "
                f"{n + 1} ({nxt.task}, at {nxt.location}). The rest of the work toward {cp_to.id.upper()} "
                f"({cp_to.state}) is NOT done yet. {self._lock(cp_from.camera)}")

    def _previous_built(self, cp: Checkpoint) -> tuple[str, ...]:
        i = [c.id for c in self.checkpoints].index(cp.id)
        return self.checkpoints[i - 1].built if i > 0 else ()


def load_spec(path: Path) -> ProjectSpec:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise SpecError(f"Cannot read project spec {path}: {e}") from e
    try:
        checkpoints = [Checkpoint(c["id"], c["title"], c["state"], c["camera"], tuple(c.get("built", ())),
                                  dict(c.get("materials", {})), tuple(c.get("tools_in_view", ())))
                       for c in raw.get("checkpoints", [])]
        shots = [Shot(s["id"], s["from"], s["to"], s["title"], s["complexity"], s["shot_class"],
                      tuple(Beat(b["task"], b["location"], int(b.get("duration_seconds", 3))) for b in s.get("beats", [])),
                      bool(s.get("camera_moves", False)), bool(s.get("proof", False)), s.get("model"))
                 for s in raw.get("shots", [])]
        spec = ProjectSpec(raw["slug"], raw["name"], raw["status"], float(raw["budget"]["cap_usd"]),
                           float(raw["budget"]["per_clip_max_usd"]), raw.get("concept"), dict(raw.get("bibles", {})),
                           dict(raw.get("cameras", {})), checkpoints, shots)
    except (KeyError, TypeError, ValueError) as e:
        raise SpecError(f"Project spec {path} is malformed: {e!r}") from e
    for shot in spec.shots:
        if shot.shot_class not in SHOT_CLASSES:
            raise SpecError(f"{shot.id}: unknown shot_class {shot.shot_class!r}")
        if shot.complexity not in COMPLEXITY_CLIPS:
            raise SpecError(f"{shot.id}: unknown complexity {shot.complexity!r}")
    return spec
