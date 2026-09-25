"""Higgsfield API (api.higgsfield.ai) VideoProvider - first/last-frame models.

Higgsfield is a gateway to many vendors' models behind one request lifecycle
(docs.higgsfield.ai, checked 2026-09-24):

  - auth header        Authorization: Key {api_key_id}:{api_key_secret}
  - upload (free)      POST /files/generate-upload-url {content_type}
                         -> PUT bytes to upload_url with every upload_headers entry
                         -> pass public_url as a model input (the upload URL lives 1 h)
  - estimate (free)    POST /estimate/{endpoint_id} with the exact generation payload
                         -> {"credits": "...", "usd": "..."}
  - submit (PAID)      POST /{endpoint_id} -> {request_id, status_url, cancel_url}
  - status             GET status_url -> queued | in_progress | completed | failed | nsfw | canceled
  - cancel             POST cancel_url (queued only; refunded)

Failed/nsfw requests are not charged. Nothing in this module submits unless
submit_video_job() is called; upload_image() and estimate_payload() never spend.
"""
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.config import settings
from app.providers.base import (
    ProviderJobState,
    SubmittedVideoJob,
    VideoGenerationRequest,
    VideoJobStatusResult,
    VideoProvider,
    VideoProviderError,
)

HIGGSFIELD_API_BASE = "https://api.higgsfield.ai"


@dataclass
class HiggsfieldVideoModelConfig:
    """One Higgsfield endpoint and its request shape (from that model's own docs page)."""

    endpoint_id: str
    first_frame_param: str
    last_frame_param: str | None
    duration_min: int
    duration_max: int
    aspect_ratios: tuple[str, ...] = ()        # empty = the endpoint has no aspect_ratio field
    prompt_max_chars: int | None = None
    static_payload: dict = field(default_factory=dict)  # always sent, e.g. mode, sound, multi_shots


# docs.higgsfield.ai/docs/models/kling-o3/first-last-frame (schema checked 2026-09-24):
# first_frame_url required, last_frame_url optional, mode std|pro|4k (default pro),
# sound on|off (default off), duration 3-15 int, aspect_ratio 16:9|9:16|1:1,
# multi_shots false -> prompt required; top-level prompt truncated past 2,500 chars.
KLING_O3_FIRST_LAST_FRAME = HiggsfieldVideoModelConfig(
    endpoint_id="kling-video/o3/first-last-frame",
    first_frame_param="first_frame_url",
    last_frame_param="last_frame_url",
    duration_min=3,
    duration_max=15,
    aspect_ratios=("16:9", "9:16", "1:1"),
    prompt_max_chars=2500,
    static_payload={"mode": "pro", "sound": "off", "multi_shots": False},
)


def _split_key(combined: str | None) -> tuple[str | None, str | None]:
    """HF_KEY holds "<key id>:<key secret>"; anything else is treated as not configured."""
    key_id, sep, secret = (combined or "").strip().strip("'\"").partition(":")
    return (key_id, secret) if sep and key_id and secret and ":" not in secret else (None, None)


def _content_type(path: Path) -> str:
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(
        path.suffix.lower()) or "image/jpeg"


class HiggsfieldVideoProvider(VideoProvider):
    """`client` lets tests inject an httpx.Client on a fake transport - no network, no cost."""

    def __init__(self, model_config: HiggsfieldVideoModelConfig = KLING_O3_FIRST_LAST_FRAME, *,
                 api_key_id: str | None = None, api_key_secret: str | None = None,
                 client: httpx.Client | None = None) -> None:
        self.model_config = model_config
        self.name = f"higgsfield:{model_config.endpoint_id}"
        combined_id, combined_secret = _split_key(settings.hf_key)
        self.api_key_id = api_key_id or settings.hf_api_key_id or combined_id
        self.api_key_secret = api_key_secret or settings.hf_api_key_secret or combined_secret
        self._client = client or httpx.Client(timeout=60.0)
        self._uploads: dict[str, str] = {}  # sha256 of file bytes -> public_url (reused within 1 h)
        self._estimates: dict[str, float] = {}

    def _headers(self) -> dict:
        if not (self.api_key_id and self.api_key_secret):
            raise VideoProviderError('Higgsfield key not configured: set HF_KEY="<key id>:<key secret>" in .env '
                                     "(or HF_API_KEY_ID and HF_API_KEY_SECRET).")
        return {"Authorization": f"Key {self.api_key_id}:{self.api_key_secret}"}

    @staticmethod
    def _diag(method: str, url: str) -> None:
        """Method and URL only - never headers (they carry the key)."""
        print(f"[higgsfield] {method} {url}")

    # --- free calls ---------------------------------------------------------------------------

    def upload_image(self, local_path: str | Path) -> str:
        """Upload a local image and return its public_url. Free. Cached per file content."""
        path = Path(local_path)
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest in self._uploads:
            return self._uploads[digest]
        content_type = _content_type(path)
        url = f"{HIGGSFIELD_API_BASE}/files/generate-upload-url"
        self._diag("POST", url)
        resp = self._client.post(url, headers=self._headers(), json={"content_type": content_type})
        if resp.status_code >= 400:
            raise VideoProviderError(f"Higgsfield upload-url request failed: {resp.status_code} {resp.text}")
        info = resp.json()
        upload_headers = info.get("upload_headers") or {"Content-Type": content_type}
        self._diag("PUT", info["upload_url"].split("?")[0])  # presigned query string omitted from logs
        put = self._client.put(info["upload_url"], content=data, headers=upload_headers)  # no API credentials
        if put.status_code >= 400:
            raise VideoProviderError(f"Higgsfield image upload failed: {put.status_code} {put.text[:300]}")
        self._uploads[digest] = info["public_url"]
        return info["public_url"]

    def build_payload(self, request: VideoGenerationRequest) -> dict:
        """Validate the request against this endpoint's schema and build the exact payload.
        Uploads the frames (free). Refuses rather than silently dropping or altering anything."""
        cfg = self.model_config
        if not request.reference_image_path:
            raise VideoProviderError(f"{cfg.endpoint_id} needs a first frame; none was provided.")
        if request.end_image_path and not cfg.last_frame_param:
            raise VideoProviderError(f"{cfg.endpoint_id} has no last-frame input; refusing to drop the end frame.")
        duration = request.duration_seconds
        if duration != int(duration) or not cfg.duration_min <= duration <= cfg.duration_max:
            raise VideoProviderError(f"{cfg.endpoint_id} takes a whole-second duration "
                                     f"{cfg.duration_min}-{cfg.duration_max}; got {duration}.")
        if cfg.aspect_ratios and request.aspect_ratio not in cfg.aspect_ratios:
            raise VideoProviderError(f"{cfg.endpoint_id} aspect ratio must be one of {cfg.aspect_ratios}.")
        if cfg.prompt_max_chars and len(request.prompt) > cfg.prompt_max_chars:
            raise VideoProviderError(f"Prompt is {len(request.prompt)} chars; {cfg.endpoint_id} truncates past "
                                     f"{cfg.prompt_max_chars} - refusing to send a truncated prompt.")
        payload = {"prompt": request.prompt,
                   cfg.first_frame_param: self.upload_image(request.reference_image_path)}
        if request.end_image_path:
            payload[cfg.last_frame_param] = self.upload_image(request.end_image_path)
        if cfg.aspect_ratios:
            payload["aspect_ratio"] = request.aspect_ratio
        payload["duration"] = int(duration)
        payload.update(cfg.static_payload)
        for key in ("mode", "sound"):  # documented per-request overrides only
            if key in request.extra_params:
                payload[key] = request.extra_params[key]
        return payload

    def estimate_payload(self, payload: dict) -> dict:
        """Higgsfield's own price for this exact payload. Free - never generates."""
        url = f"{HIGGSFIELD_API_BASE}/estimate/{self.model_config.endpoint_id}"
        self._diag("POST", url)
        resp = self._client.post(url, headers=self._headers(), json=payload)
        if resp.status_code >= 400:
            raise VideoProviderError(f"Higgsfield estimate failed: {resp.status_code} {resp.text}")
        data = resp.json()
        try:
            return {"usd": float(data["usd"]), "credits": float(data["credits"]), "raw": data}
        except (KeyError, TypeError, ValueError) as e:
            raise VideoProviderError(f"Higgsfield estimate response not understood: {data}") from e

    def estimate_cost(self, request: VideoGenerationRequest) -> float:
        payload = self.build_payload(request)
        usd = self.estimate_payload(payload)["usd"]
        self._estimates[self._key(payload)] = usd
        return usd

    @staticmethod
    def _key(payload: dict) -> str:
        return hashlib.sha256(repr(sorted(payload.items())).encode()).hexdigest()

    # --- paid call ----------------------------------------------------------------------------

    def submit_video_job(self, request: VideoGenerationRequest) -> SubmittedVideoJob:
        """PAID. Submits exactly one generation of the payload build_payload() produces."""
        payload = self.build_payload(request)
        estimate = self._estimates.get(self._key(payload))
        if estimate is None:
            estimate = self.estimate_payload(payload)["usd"]
        url = f"{HIGGSFIELD_API_BASE}/{self.model_config.endpoint_id}"
        self._diag("POST", url)
        resp = self._client.post(url, headers=self._headers(), json=payload)
        if resp.status_code >= 400:
            raise VideoProviderError(f"Higgsfield submit failed: {resp.status_code} {resp.text}")
        data = resp.json()
        if not data.get("request_id"):
            raise VideoProviderError(f"Higgsfield submit returned no request_id: {data}")
        return SubmittedVideoJob(provider_name=self.name, provider_job_id=data["request_id"],
                                 estimated_cost_usd=estimate,
                                 meta={"status_url": data.get("status_url"), "cancel_url": data.get("cancel_url"),
                                       "endpoint_id": self.model_config.endpoint_id})

    # --- status / recovery (free) -------------------------------------------------------------

    def get_job_status(self, provider_job_id: str, meta: dict | None = None) -> VideoJobStatusResult:
        meta = meta or {}
        url = meta.get("status_url") or f"{HIGGSFIELD_API_BASE}/requests/{provider_job_id}/status"
        self._diag("GET", url)
        try:
            resp = self._client.get(url, headers=self._headers())
        except httpx.HTTPError as e:
            raise VideoProviderError(f"Higgsfield status check failed: {e}") from e
        if resp.status_code >= 400:
            raise VideoProviderError(f"Higgsfield status check failed: {resp.status_code} {resp.text}")
        data = resp.json()
        status = data.get("status")
        if status in ("queued", "in_progress"):
            return VideoJobStatusResult(status=ProviderJobState.PROCESSING, meta={"provider_status": status})
        if status == "completed":
            video_url = (data.get("video") or {}).get("url")
            if not video_url:
                raise VideoProviderError(f"Higgsfield result had no video URL: {data}")
            return VideoJobStatusResult(status=ProviderJobState.COMPLETED, output_url=video_url)
        # failed / nsfw / canceled are terminal and not charged.
        return VideoJobStatusResult(status=ProviderJobState.FAILED, actual_cost_usd=0.0,
                                    error_message=f"Higgsfield reported {status!r}: {data.get('error') or data}",
                                    meta={"provider_status": status})

    def cancel(self, provider_job_id: str, meta: dict | None = None) -> dict:
        """Cancel a still-queued request (refunded). Fails once generation has started."""
        url = (meta or {}).get("cancel_url") or f"{HIGGSFIELD_API_BASE}/requests/{provider_job_id}/cancel"
        self._diag("POST", url)
        resp = self._client.post(url, headers=self._headers())
        if resp.status_code >= 400:
            raise VideoProviderError(f"Higgsfield cancel failed: {resp.status_code} {resp.text}")
        return resp.json() if resp.content else {}

    def download_result(self, provider_job_id: str, output_url: str, destination_path: str) -> str:
        self._diag("GET", output_url)
        resp = self._client.get(output_url)
        if resp.status_code >= 400:
            raise VideoProviderError(f"Higgsfield clip download failed: {resp.status_code}")
        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return str(dest)
