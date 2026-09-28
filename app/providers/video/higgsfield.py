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
import math
import re
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
    # Empty = the endpoint has no aspect_ratio field: framing follows the first frame, so the first
    # frame's own shape is checked against the requested aspect ratio instead.
    aspect_ratios: tuple[str, ...] = ()
    prompt_max_chars: int | None = None
    static_payload: dict = field(default_factory=dict)  # always sent, e.g. mode, sound, multi_shots
    request_overrides: tuple[str, ...] = ()  # documented fields a request may set via extra_params
    # Token-priced models: /estimate answers with a pricing description instead of a number. The price
    # is then computed from the published per-1,000-token rate (which must still appear verbatim in
    # that description) and a conservative output size per resolution tier.
    token_rate_per_1k_usd: dict[str, float] = field(default_factory=dict)
    token_output_px_upper: dict[str, tuple[int, int]] = field(default_factory=dict)


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
    request_overrides=("mode", "sound"),
)

# docs.higgsfield.ai/docs/models/seedance-2-5/image-to-video (schema checked 2026-09-27):
# image_url required, end_image_url optional (last frame), duration 4-30 int, resolution 480p|720p
# (default 720p), bitrate_mode standard|high (default high), generate_audio bool (default TRUE),
# additionalProperties false - there is NO aspect_ratio field: "output framing follows image_url".
SEEDANCE_2_5_IMAGE_TO_VIDEO = HiggsfieldVideoModelConfig(
    endpoint_id="bytedance/seedance-2.5/image-to-video",
    first_frame_param="image_url",
    last_frame_param="end_image_url",
    duration_min=4,
    duration_max=30,
    static_payload={"resolution": "480p", "generate_audio": False},
    request_overrides=("resolution", "bitrate_mode", "generate_audio"),
    # From the /estimate pricing description (2026-09-27): "Each 1,000 video tokens costs $0.0214 at
    # 480p or 720p"; tokens = ceil(h x w x seconds x 24 / 1024). The exact 9:16 output size isn't
    # documented (480p is ~480x854), so the upper bound uses the long side rounded up to 16 px.
    token_rate_per_1k_usd={"480p": 0.0214, "720p": 0.0214},
    token_output_px_upper={"480p": (480, 864), "720p": (720, 1280)},
)

MODELS = {c.endpoint_id: c for c in (KLING_O3_FIRST_LAST_FRAME, SEEDANCE_2_5_IMAGE_TO_VIDEO)}


def image_size(path: str | Path) -> tuple[int, int]:
    """(width, height) of a JPEG or PNG from its header - no imaging library needed."""
    data = Path(path).read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker, seg_len = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + seg_len
    raise VideoProviderError(f"Can't read the image size of {Path(path).name} (JPEG or PNG expected).")


def _ratio_matches(width: int, height: int, aspect_ratio: str, tolerance: float = 0.02) -> bool:
    w, h = (float(x) for x in aspect_ratio.split(":"))
    return abs((width / height) / (w / h) - 1) <= tolerance


def _split_key(combined: str | None) -> tuple[str | None, str | None]:
    """HF_KEY holds "<key id>:<key secret>"; anything else is treated as not configured."""
    key_id, sep, secret = (combined or "").strip().strip("'\"").partition(":")
    return (key_id, secret) if sep and key_id and secret and ":" not in secret else (None, None)


def _token_rates(description: str) -> dict[str, float]:
    """Per-1,000-token rates by tier from the pricing description, e.g. "Each 1,000 video tokens costs
    $0.0214 at 480p or 720p and $0.0234 at 1080p" -> {"480p": 0.0214, "720p": 0.0214, "1080p": 0.0234}."""
    sentence = re.search(r"1,000 video tokens costs([^.]*(?:\.\d[^.]*)*)", description)
    rates: dict[str, float] = {}
    for price, tiers in re.findall(r"\$(\d+\.\d+) at ((?:\d+p)(?:(?:,\s*|\s+or\s+)\d+p)*)",
                                   sentence.group(1) if sentence else ""):
        rates.update({tier: float(price) for tier in re.findall(r"\d+p", tiers)})
    return rates


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
        if not cfg.aspect_ratios and request.aspect_ratio:
            width, height = image_size(request.reference_image_path)
            if not _ratio_matches(width, height, request.aspect_ratio):
                raise VideoProviderError(f"{cfg.endpoint_id} has no aspect_ratio field - framing follows the first "
                                         f"frame, which is {width}x{height}, not {request.aspect_ratio}.")
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
        unknown = set(request.extra_params) - set(cfg.request_overrides)
        if unknown:
            raise VideoProviderError(f"{cfg.endpoint_id} does not accept {sorted(unknown)} - refusing rather than "
                                     "dropping them.")
        payload.update(request.extra_params)
        return payload

    def estimate_payload(self, payload: dict) -> dict:
        """Higgsfield's own price for this exact payload. Free - never generates."""
        url = f"{HIGGSFIELD_API_BASE}/estimate/{self.model_config.endpoint_id}"
        self._diag("POST", url)
        resp = self._client.post(url, headers=self._headers(), json=payload)
        if resp.status_code >= 400:
            raise VideoProviderError(f"Higgsfield estimate failed: {resp.status_code} {resp.text}")
        data = resp.json()
        if "usd" in data:
            try:
                return {"usd": float(data["usd"]), "credits": float(data["credits"]), "raw": data,
                        "basis": "Higgsfield /estimate (exact)"}
            except (KeyError, TypeError, ValueError) as e:
                raise VideoProviderError(f"Higgsfield estimate response not understood: {data}") from e
        if data.get("type") == "description":
            return self._token_price(payload, data)
        raise VideoProviderError(f"Higgsfield estimate response not understood: {data}")

    def _token_price(self, payload: dict, data: dict) -> dict:
        """Upper-bound price from the token formula when /estimate only describes the pricing."""
        cfg, text = self.model_config, data.get("pricing_description") or ""
        tier = payload.get("resolution")
        rate, size = cfg.token_rate_per_1k_usd.get(tier), cfg.token_output_px_upper.get(tier)
        if rate is None or size is None:
            raise VideoProviderError(f"{cfg.endpoint_id} returned no price and has no token rate on file for "
                                     f"{tier!r}: {text}")
        if _token_rates(text).get(tier) != rate:
            raise VideoProviderError(f"{cfg.endpoint_id} pricing changed - ${rate:.4f}/1k tokens at {tier} is no "
                                     f"longer in Higgsfield's description; re-check before spending: {text}")
        width, height = size
        tokens = math.ceil(width * height * payload["duration"] * 24 / 1024)
        return {"usd": round(tokens * rate / 1000, 4), "credits": None, "raw": data, "tokens": tokens,
                "basis": f"token formula upper bound: ceil({width}x{height}x{payload['duration']}s x 24/1024) = "
                         f"{tokens} tokens x ${rate}/1k"}

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
