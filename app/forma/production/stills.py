"""Manual stills: made in ChatGPT, uploaded through the studio (or dropped in the folder), approved by a person.

Entirely local - no API calls, nothing generated. The stills folder is the source of truth:

    <project>/stills/<key>.<jpg|png|webp>      exactly one file per key
    <project>/stills/_replaced/<key>__<utc>.<ext>   every file an upload replaced (never deleted)

State (the same rules the train-car CLI uses):
    missing   no file for the key
    placed    a file exists, never approved
    approved  the file's sha256 is the approved one
    changed   the file is not the approved one (replaced after approval) - re-approve before any clip uses it
    ambiguous several files for one key

Uploads are recorded in manifest["still_uploads"][key]; approvals in manifest[key] (output_path,
approved_sha256, approved_via "manual") - the same shape the importer and the train-car tools read.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from app.forma.production.spec import STILL_EXTENSIONS

MAX_UPLOAD_BYTES = 30 * 1024 * 1024
_TYPES = {"jpeg": ".jpg", "png": ".png", "webp": ".webp"}


class StillError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stills_dir(manifest_path: Path) -> Path:
    return Path(manifest_path).parent / "stills"


def sniff(data: bytes) -> tuple[str, int, int]:
    """(type, width, height) from the file header; refuses anything that is not a real JPEG/PNG/WebP."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return "png", int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker, seg_len = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return "jpeg", int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            i += 2 + seg_len
        raise StillError("JPEG without a readable size header.")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8X":
            return "webp", 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if chunk == b"VP8 ":
            return "webp", int.from_bytes(data[26:28], "little") & 0x3FFF, int.from_bytes(data[28:30], "little") & 0x3FFF
        if chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return "webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise StillError("Not a JPEG, PNG or WebP image (checked the file contents, not just the name).")


_SHA_CACHE: dict[tuple[str, int, int], str] = {}


def file_sha256(path: Path) -> str:
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key not in _SHA_CACHE:
        _SHA_CACHE[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return _SHA_CACHE[key]


def _files(manifest_path: Path, key: str) -> list[Path]:
    d = stills_dir(manifest_path)
    return [d / f"{key}{ext}" for ext in STILL_EXTENSIONS if (d / f"{key}{ext}").is_file()]


def _read(manifest_path: Path) -> dict:
    return json.loads(Path(manifest_path).read_text())


def _write(manifest_path: Path, manifest: dict) -> None:
    tmp = Path(manifest_path).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2))
    os.replace(tmp, manifest_path)


def state(manifest_path: Path, key: str, manifest: dict | None = None) -> dict:
    manifest = manifest if manifest is not None else _read(manifest_path)
    files = _files(manifest_path, key)
    entry = manifest.get(key) if isinstance(manifest.get(key), dict) else {}
    if len(files) > 1:
        return {"state": "ambiguous", "paths": [str(f) for f in files]}
    if not files:
        return {"state": "missing", "expected": str(stills_dir(manifest_path) / f"{key}.jpg")}
    path, digest = files[0], file_sha256(files[0])
    approved = entry.get("approved_sha256")
    if approved is None:
        st = "placed"
    elif approved == digest and Path(entry.get("output_path", "")) == path:
        st = "approved"
    else:
        st = "changed"
    return {"state": st, "path": str(path), "sha256": digest}


def info(manifest_path: Path, key: str, *, label: str, dependents: list[str], manifest: dict | None = None,
         brief: str | None = None, media_url=None) -> dict:
    """Everything the studio shows for one manual still (local reads only)."""
    manifest = manifest if manifest is not None else _read(manifest_path)
    st = state(manifest_path, key, manifest)
    entry = manifest.get(key) if isinstance(manifest.get(key), dict) else {}
    out = {"key": key, "label": label, "state": st["state"], "expected_filename": f"{key}.jpg | .png | .webp",
           "expected_dir": str(stills_dir(manifest_path)), "path": st.get("path"), "sha256": st.get("sha256"),
           "approved_sha256": entry.get("approved_sha256"), "approved_at": entry.get("approved_at"),
           "approval_note": entry.get("approval_note"), "brief": brief,
           "upload": (manifest.get("still_uploads") or {}).get(key), "width": None, "height": None,
           "file_type": None, "size_bytes": None, "url": None}
    if st.get("path"):
        path = Path(st["path"])
        try:
            kind, w, h = sniff(path.read_bytes()[:65536])
            out.update(file_type=kind, width=w, height=h)
        except StillError:
            out["file_type"] = "unreadable"
        out["size_bytes"] = path.stat().st_size
        out["url"] = media_url(str(path)) if media_url else None
    approved = entry.get("approved_sha256")
    out["used_by"] = [{"clip": clip, **_clip_use(manifest, clip, key, approved, st["state"])} for clip in dependents]
    return out


def _used_hash(record: dict, side: str, key: str) -> str | None:
    """The hash of `key` a clip record was generated from, if that side of the clip used this still."""
    named = record.get(f"{side}_still") == key or Path(record.get(f"{side}_frame_path") or "").stem == key
    return record.get(f"{side}_frame_sha256") if named else None


def _clip_use(manifest: dict, clip: str, key: str, approved: str | None, still_state: str) -> dict:
    """Has this clip been generated from this still, and was that from a version that is no longer approved?"""
    records = [v for k, v in manifest.items()
               if isinstance(v, dict) and (k == clip or k.startswith(f"{clip}__attempt")) and v.get("provider_job_id")]
    used = {h for r in records for h in (_used_hash(r, "start", key), _used_hash(r, "end", key)) if h}
    return {"generated": bool(records),
            "stale": bool(used) and (still_state != "approved" or approved not in used)}


def upload(manifest_path: Path, key: str, filename: str, data: bytes, *, replace: bool = False) -> dict:
    """Save an uploaded still as <key>.<ext> in the project's stills folder. Never approves it.

    If a file for the key exists, `replace=True` is required; the old file is moved to stills/_replaced/
    (never deleted). A replaced approved still becomes `changed` until approved again."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise StillError(f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.", 413)
    if Path(filename).suffix.lower() not in STILL_EXTENSIONS:
        raise StillError(f"Accepted formats: {', '.join(STILL_EXTENSIONS)}.", 415)
    kind, width, height = sniff(data)
    d = stills_dir(manifest_path)
    d.mkdir(parents=True, exist_ok=True)
    existing = _files(manifest_path, key)
    manifest = _read(manifest_path)
    before = state(manifest_path, key, manifest) if existing else {"state": "missing"}
    if existing and not replace:
        raise StillError(f"{key} already has a still ({before['state']}: {existing[0].name}). Confirm replacement "
                         "to upload over it - the current file is kept in stills/_replaced/.", 409)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archived = []
    for old in existing:
        dest = d / "_replaced" / f"{key}__{stamp}{old.suffix.lower()}"
        dest.parent.mkdir(exist_ok=True)
        os.replace(old, dest)
        archived.append(str(dest))
    target = d / f"{key}{_TYPES[kind]}"
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    digest = file_sha256(target)
    record = {"sha256": digest, "stored_as": str(target), "original_filename": Path(filename).name,
              "file_type": kind, "width": width, "height": height, "size_bytes": len(data), "uploaded_at": _now(),
              "source": "studio upload"}
    if archived:
        record["replaced"] = {"previous_state": before["state"], "previous_sha256": before.get("sha256"),
                              "archived_to": archived}
    manifest = _read(manifest_path)  # re-read right before writing
    manifest.setdefault("still_uploads", {})[key] = record
    _write(manifest_path, manifest)
    return {"key": key, **record, "state": state(manifest_path, key)["state"]}


def approve(manifest_path: Path, key: str, note: str) -> dict:
    """Record the still currently in the folder as approved (a person looked at it). Free, local."""
    if not note.strip():
        raise StillError("Say what you checked (a short note) when approving a still.")
    manifest = _read(manifest_path)
    st = state(manifest_path, key, manifest)
    if st["state"] in ("missing", "ambiguous"):
        raise StillError(f"{key}: nothing to approve ({st['state']}).", 409)
    now = _now()
    entry = manifest.get(key) if isinstance(manifest.get(key), dict) else None
    if entry is not None and entry.get("approved_sha256") not in (None, st["sha256"]):
        n = 1
        while f"{key}__attempt{n}" in manifest:
            n += 1
        manifest[f"{key}__attempt{n}"] = entry | {"archived_at": now, "archive_reason": "replaced by a newer still"}
        entry = None
    entry = entry or {"source": "manual", "actual_cost_usd": 0.0}
    entry.update(output_path=st["path"], completed_at=now, approved_sha256=st["sha256"], approved_at=now,
                 approved_via="manual", approval_note=note.strip())
    manifest[key] = entry
    _write(manifest_path, manifest)
    return {"key": key, **entry, "state": "approved"}


def approved_file(manifest_path: Path, key: str) -> tuple[Path, str]:
    """The exact approved file and hash a clip must use - refuses anything not approved."""
    st = state(manifest_path, key)
    if st["state"] != "approved":
        raise StillError(f"{key} is {st['state']} - it must be approved before a clip can use it.", 409)
    return Path(st["path"]), st["sha256"]
