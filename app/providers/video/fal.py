"""Real fal.ai-backed VideoProvider for Alibaba's Wan 2.2 A14B family.

This has now been exercised against the live API (image + video submit both
succeeded in a real test), which caught two real bugs in the status/result
URL construction - see FalVideoModelConfig.queue_app_id's docstring for
what was wrong and how it was verified against fal.ai's own official
Python client source. get_job_status() now prefers the status_url/
response_url fal.ai itself returns at submission time (same approach fal's
own client uses) rather than reconstructing URLs, which is the more robust
fix; the queue_app_id-based reconstruction is only a fallback for when that
isn't available (e.g. recovering an old job).

Configurable between named model presets via `FalVideoModelConfig` - swap
which one is active by passing a different config to FalVideoProvider,
without touching any other code. Two are defined below (Turbo and
standard); adding a third fal.ai model (or a different provider entirely,
e.g. Kling/Veo later) means adding one more config/class, not editing this
one.
"""
import math
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

FAL_QUEUE_BASE = "https://queue.fal.run"
FAL_STORAGE_BASE = "https://rest.alpha.fal.ai"


@dataclass
class FalVideoModelConfig:
    """One named, swappable fal.ai video model configuration.

    `base_model_id` and `subpath` are deliberately separate fields, not one
    combined path string - fal.ai's queue API documents this explicitly:
    "the subpath should be used when making the request, but not when
    getting request status or results." Turbo is a subpath variant of the
    same base Wan app, so submission uses base_model_id/subpath together,
    but status/result checks use base_model_id alone. Getting this wrong
    (using the full path for status too) returns HTTP 405 - that's the bug
    this split fixes.
    """

    base_model_id: str
    billing: str  # "flat" (price_by_resolution) or "per_second" (price_per_second_by_resolution)
    subpath: str | None = None
    price_by_resolution: dict[str, float] = field(default_factory=dict)
    price_per_second_by_resolution: dict[str, float] = field(default_factory=dict)
    default_resolution: str = "480p"

    # Per-model request-shape differences, verified against each model's own
    # docs before use (see the bake-off research) rather than assumed from
    # Wan's shape:
    image_param_name: str = "image_url"  # Kling uses "start_image_url" instead
    # Last-frame conditioning field, or None if the model has none. A request with
    # an end image is refused for models without one - never silently dropped.
    end_image_param_name: str | None = None
    supports_resolution_param: bool = True  # Kling has no selectable resolution param
    extra_payload: dict = field(default_factory=dict)  # static fields always sent, e.g. duration, generate_audio

    # --- Fields used by the Project #3 configs (all default to the original behaviour) ---
    # "tokens" billing: fal's published formula ceil(h x w x seconds x 24 / 1024) tokens at
    # price_per_1k_tokens, using the 9:16 output size in token_dims_by_resolution (an upper bound).
    price_per_1k_tokens: float | None = None
    token_dims_by_resolution: dict[str, tuple[int, int]] = field(default_factory=dict)
    send_aspect_ratio: bool = True  # False where the model takes the aspect from the start image
    # Duration taken from the request (not pinned in extra_payload): field name, format and the
    # values the schema allows. Anything else is refused, never rounded.
    duration_param: str | None = None
    duration_format: str = "{}"  # "{}s" for Veo ("6s")
    allowed_durations: tuple[int, ...] = ()
    # The model's audio toggle; when set it is ALWAYS sent as False (FORMA adds sound in the edit).
    audio_off_param: str | None = None
    requires_end_image: bool = False  # Veo first-last-frame has no single-image mode
    supports_multi_prompt: bool = False  # Kling v3: extra_params["multi_prompt"] replaces "prompt"
    # extra_params keys passed through as-is (the original Wan whitelist unless a config says otherwise).
    passthrough_params: tuple[str, ...] = ("enable_prompt_expansion", "seed", "acceleration")

    @property
    def submit_path(self) -> str:
        """The path used ONLY for submitting a new job (includes the subpath, if any)."""
        return f"{self.base_model_id}/{self.subpath}" if self.subpath else self.base_model_id

    @property
    def queue_app_id(self) -> str:
        """The path fal.ai's queue actually tracks requests under for
        status/result lookups - verified against fal.ai's own official
        Python client source (fal_client.client.AppId.from_endpoint_id):
        only the first two path segments (owner/alias) matter, e.g.
        "fal-ai/wan" - NOT "fal-ai/wan/v2.2-a14b/image-to-video" and
        NOT the submission subpath ("turbo"). Everything after the first
        two segments is routing used only when submitting a job; the
        queue's request/status/result tracking lives at the owner/alias
        level. This was the second bug (the first fix stripped only the
        subpath, which still 405'd - it needed to strip the whole
        "v2.2-a14b/image-to-video" tail too)."""
        segments = self.base_model_id.split("/")
        return "/".join(segments[:2])


# Cheapest-first candidate: flat per-video pricing, not per-second.
# Re-verified (Sept 2026): the endpoint takes a `num_frames` param, 81-100
# inclusive, default 81 (~5.06s @ 16fps) - >81 frames bills at a 1.25x
# multiplier, breaking the flat price_by_resolution rate below. `num_frames`
# is pinned to 81 explicitly here (not left to the API's own default) so
# this config can never silently drift onto the 1.25x tier if fal.ai ever
# changes its default - resolution stays the only cost lever we intend to
# vary. (Earlier project notes assumed a fixed ~4s/65-frame output; this
# supersedes that - 81 frames is fal.ai's own current documented default.)
WAN_TURBO = FalVideoModelConfig(
    base_model_id="fal-ai/wan/v2.2-a14b/image-to-video",
    subpath="turbo",
    billing="flat",
    price_by_resolution={"480p": 0.05, "580p": 0.075, "720p": 0.10},
    default_resolution="480p",
    extra_payload={"num_frames": 81},
)

# Higher-quality, non-turbo alternative, billed per second of output
# instead of a flat rate. Kept available so an individual important shot
# can be upgraded later just by passing this config instead of WAN_TURBO.
# No subpath - this endpoint IS the base app.
WAN_STANDARD = FalVideoModelConfig(
    base_model_id="fal-ai/wan/v2.2-a14b/image-to-video",
    billing="per_second",
    price_per_second_by_resolution={"480p": 0.04, "580p": 0.06, "720p": 0.08},
    default_resolution="480p",
)

# Quality bake-off candidate. No subpath - the whole path is the app itself,
# so queue_app_id = "fal-ai/kling-video" (owner/alias only, same rule as Wan).
# Verified: no selectable "resolution" param (quality is inherent to the
# pro tier, described as "up to 1080p"), so billing uses a single synthetic
# "default" resolution key rather than a real tier. Image field is
# "start_image_url", not "image_url" - a genuine per-model difference from
# Wan, confirmed via fal.ai's own docs before use. cfg_scale is deliberately
# NOT set here - fal.ai's documented default (0.5) applies, per instruction
# not to push it toward an extreme for a fair bake-off comparison.
KLING_2_6_PRO = FalVideoModelConfig(
    base_model_id="fal-ai/kling-video/v2.6/pro/image-to-video",
    billing="per_second",
    price_per_second_by_resolution={"default": 0.07},
    default_resolution="default",
    image_param_name="start_image_url",
    supports_resolution_param=False,
    extra_payload={
        "duration": "5",  # must match VideoGenerationRequest.duration_seconds=5.0 for cost math to agree
        "generate_audio": False,
        "negative_prompt": "blur, distort, low quality",  # fal's own documented example usage
    },
)

# Quality bake-off candidate. No subpath - queue_app_id = "fal-ai/veo3.1".
# Price is identical at 720p and 1080p for the Fast tier, so 1080p is a free
# quality upgrade. duration is a string like "6s", not a bare number -
# another genuine per-model difference from both Wan and Kling.
VEO_3_1_FAST = FalVideoModelConfig(
    base_model_id="fal-ai/veo3.1/fast/image-to-video",
    billing="per_second",
    price_per_second_by_resolution={"720p": 0.10, "1080p": 0.10},
    default_resolution="1080p",
    extra_payload={
        "duration": "6s",  # must match VideoGenerationRequest.duration_seconds=6.0 for cost math to agree
        "generate_audio": False,
    },
)

# One-time premium benchmark candidate (not a production model) - verified
# against fal.ai's own seedance-2.0-api repository schema. No subpath split
# on resolution the way Wan is - Fast bills a flat $0.2419/s regardless of
# whether "480p" or "720p" is requested (the two tiers differ by resolution
# CEILING, not by price: Standard adds 1080p access at a higher $0.3024/s
# flat rate, not used here). queue_app_id = "bytedance/seedance-2.0" by the
# same owner/alias-only rule verified for Wan/Kling/Veo - not yet exercised
# against the live queue for this specific app, so get_job_status()'s
# preference for the server-returned status_url/response_url (see
# FalVideoProvider.get_job_status) is what actually matters in practice,
# not this reconstruction fallback.
SEEDANCE_2_0_FAST = FalVideoModelConfig(
    base_model_id="bytedance/seedance-2.0",
    subpath="fast/image-to-video",
    billing="per_second",
    price_per_second_by_resolution={"480p": 0.2419, "720p": 0.2419},
    default_resolution="720p",
    extra_payload={
        "duration": "8",  # plain digit string, not "8s" - must match duration_seconds=8.0
        "generate_audio": True,  # verified: fal.ai bills the same whether audio is on or off
    },
)

# Cost-down candidate for a single ~15s continuous generation (owner
# "alibaba", a third distinct owner after "fal-ai" and "bytedance" - queue
# routing again resolves to owner/alias only: "alibaba/wan-3.0"). HIGH
# CONFIDENCE, cross-confirmed across multiple fal.ai model-page searches:
# endpoint path, 2-30s duration range (15s comfortably inside it),
# 480p/720p/1080p resolution tiers, 9:16 aspect ratio support, and
# per-second pricing ($0.05/$0.10/$0.20 at 480p/720p/1080p for the
# standard - not "Prime" - tier).
#
# UNRESOLVED despite 7 search attempts (fal.ai itself is unreachable from
# this sandbox - egress-blocked - so this could not be confirmed the way
# Seedance's was, against an actual schema repo): the exact audio-control
# field's name and type. Sources disagree on whether it's a boolean flag
# (some call it "sound", others "enable_audio") or governed implicitly by
# the prompt text itself. Resolved here by NOT setting any audio field at
# all - omitting it avoids guessing a wrong field name, and every source
# agrees audio is either on-by-default or free either way, so omission
# doesn't cost anything or contradict the experiment's needs (no audio
# required). `duration` is sent as a bare int (`15`, not `"15"` or
# `"15s"`) based on the one concrete code example found using this shape -
# also not fully certain. Both choices fail safely: fal.ai validates a
# submission's schema before any billable work starts, so a wrong field
# name/type here means an immediate 4xx at submission time, not a paid
# generation - the same zero-retry `fail()` pattern every script in this
# project already uses would simply stop with a clear diagnostic and
# nothing charged.
#
# CONFIRMED BY A REAL LIVE 422 (not secondhand research): the first real
# submission attempt was rejected with fal's own validation error - "body
# -> start_image_url: Field required" - while our payload sent "image_url".
# This endpoint uses "start_image_url", the same field name Kling uses
# (KLING_2_6_PRO below), NOT the "image_url" every Wan A14B/Veo config
# uses. Fixed via image_param_name, the same mechanism that already
# handles this exact kind of per-model difference - no new code needed,
# just the correct value for this field. duration/resolution/aspect_ratio
# were not flagged as errors in that same 422, so they're now believed
# correct (still not "confirmed" the way a successful submission would
# be - a 422 lists what's wrong, not everything that's right).
WAN_3_0_STANDARD = FalVideoModelConfig(
    base_model_id="alibaba/wan-3.0",
    subpath="image-to-video",
    billing="per_second",
    price_per_second_by_resolution={"480p": 0.05, "720p": 0.10, "1080p": 0.20},
    default_resolution="480p",
    image_param_name="start_image_url",  # confirmed via live 422 - see note above
    # First/last-frame: "end_image_url" (optional, requires start_image_url), per
    # fal's published API schema for this endpoint (checked 2026-09-24; not yet
    # exercised by a live call in this repo). Same per-second price.
    end_image_param_name="end_image_url",
    extra_payload={
        "duration": 15,  # bare int, not a string - see note above
    },
)


# ---------------------------------------------------------------------------
# Project #3 video models (2026-09-28). Every field below was checked against
# fal's own queue OpenAPI schema for the endpoint
# (https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=...) and prices
# against each model page. Audio is always forced off (FORMA adds sound in the
# edit, and on Veo/Kling audio raises the price). Durations come from the
# request and are refused if the schema doesn't allow them. Which shot class
# may use which model - and whether it is proven - lives in app/forma/routing.py.
# ---------------------------------------------------------------------------

_KLING_V3 = dict(
    billing="per_second",
    default_resolution="default",  # no resolution param; quality is inherent to the tier
    image_param_name="start_image_url",
    end_image_param_name="end_image_url",
    supports_resolution_param=False,
    send_aspect_ratio=False,  # no aspect_ratio field: the start image's 9:16 frame decides
    duration_param="duration",  # string enum "3".."15"
    allowed_durations=tuple(range(3, 16)),
    audio_off_param="generate_audio",  # default true; audio on is +50%
    supports_multi_prompt=True,  # list of {prompt, duration "1".."15"}; replaces "prompt"
    passthrough_params=("shot_type", "negative_prompt", "cfg_scale"),
)
# $0.084/s audio off. Tier 2 CANDIDATE (unproven) for repetitive labor with internal cuts.
KLING_3_STANDARD = FalVideoModelConfig(
    base_model_id="fal-ai/kling-video/v3/standard/image-to-video",
    price_per_second_by_resolution={"default": 0.084},
    **_KLING_V3,
)
# $0.112/s audio off. Same schema as Standard.
KLING_3_PRO = FalVideoModelConfig(
    base_model_id="fal-ai/kling-video/v3/pro/image-to-video",
    price_per_second_by_resolution={"default": 0.112},
    **_KLING_V3,
)

# Dedicated first/last-frame endpoint: both frames REQUIRED, named first_frame_url /
# last_frame_url. $0.10/s audio off at 720p or 1080p; duration "4s" / "6s" / "8s".
VEO_3_1_FAST_FIRST_LAST = FalVideoModelConfig(
    base_model_id="fal-ai/veo3.1/fast/first-last-frame-to-video",
    billing="per_second",
    price_per_second_by_resolution={"720p": 0.10, "1080p": 0.10},
    default_resolution="720p",
    image_param_name="first_frame_url",
    end_image_param_name="last_frame_url",
    requires_end_image=True,
    duration_param="duration",
    duration_format="{}s",
    allowed_durations=(4, 6, 8),
    audio_off_param="generate_audio",
    passthrough_params=("seed", "negative_prompt"),
)

# 9:16 output sizes used for token pricing - upper bounds (480p taken as 480x864).
_SEEDANCE_9x16 = {"480p": (480, 864), "720p": (720, 1280), "1080p": (1080, 1920)}

# Seedance 2.0 standard (not the Fast benchmark config above): $0.014 per 1k tokens at
# 480p/720p/1080p (~$0.82 for 6 s at 480p). image_url + optional end_image_url, 4-15 s.
SEEDANCE_2_0 = FalVideoModelConfig(
    base_model_id="bytedance/seedance-2.0/image-to-video",
    billing="tokens",
    price_per_1k_tokens=0.014,
    token_dims_by_resolution=_SEEDANCE_9x16,
    default_resolution="480p",
    end_image_param_name="end_image_url",
    duration_param="duration",
    allowed_durations=tuple(range(4, 16)),
    audio_off_param="generate_audio",  # same price either way; off because FORMA scores in the edit
    passthrough_params=(),
)

# Seedance 2.5: $0.0214 per 1k tokens at 480p/720p ($1.248 for 6 s at 480p - identical to what
# Higgsfield charged for the clip03 proof). aspect_ratio is "Always auto" for image-to-video, so it
# is not sent. 1080p is deliberately unpriced (no published rate) and therefore refused.
SEEDANCE_2_5 = FalVideoModelConfig(
    base_model_id="bytedance/seedance-2.5/image-to-video",
    billing="tokens",
    price_per_1k_tokens=0.0214,
    token_dims_by_resolution={k: v for k, v in _SEEDANCE_9x16.items() if k != "1080p"},
    default_resolution="480p",
    end_image_param_name="end_image_url",
    send_aspect_ratio=False,
    duration_param="duration",
    allowed_durations=tuple(range(4, 31)),
    audio_off_param="generate_audio",
    passthrough_params=(),
)

# Every fal video config by submit path - how routing and proof setups name a model.
FAL_VIDEO_MODELS: dict[str, FalVideoModelConfig] = {
    c.submit_path: c
    for c in (WAN_TURBO, WAN_STANDARD, KLING_2_6_PRO, VEO_3_1_FAST, SEEDANCE_2_0_FAST, WAN_3_0_STANDARD,
              KLING_3_STANDARD, KLING_3_PRO, VEO_3_1_FAST_FIRST_LAST, SEEDANCE_2_0, SEEDANCE_2_5)
}


class FalVideoProvider(VideoProvider):
    """Talks to fal.ai's queue API for Wan 2.2 A14B (Turbo or standard).

    The `client` param exists so tests can inject an `httpx.Client` backed by
    a fake transport (see tests/test_fal_providers.py) instead of hitting
    the network - that's how this adapter's request/response handling is
    verified without any real call or cost.
    """

    def __init__(
        self,
        model_config: FalVideoModelConfig = WAN_TURBO,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.model_config = model_config
        self.name = f"fal:{model_config.submit_path}"
        self.api_key = api_key or settings.fal_api_key
        self._client = client or httpx.Client(timeout=60.0)

    def _headers(self) -> dict:
        if not self.api_key:
            raise VideoProviderError(
                "FAL_API_KEY is not configured. Set it in .env before using a real fal.ai provider."
            )
        return {"Authorization": f"Key {self.api_key}"}

    def _resolution(self, request: VideoGenerationRequest) -> str:
        return request.extra_params.get("resolution", self.model_config.default_resolution)

    def estimate_cost(self, request: VideoGenerationRequest) -> float:
        resolution = self._resolution(request)
        if self.model_config.billing == "flat":
            price = self.model_config.price_by_resolution.get(resolution)
        elif self.model_config.billing == "tokens":
            dims = self.model_config.token_dims_by_resolution.get(resolution)
            price = None
            if dims and self.model_config.price_per_1k_tokens is not None:
                tokens = math.ceil(dims[0] * dims[1] * request.duration_seconds * 24 / 1024)
                price = tokens * self.model_config.price_per_1k_tokens / 1000
        else:
            per_second = self.model_config.price_per_second_by_resolution.get(resolution)
            price = per_second * request.duration_seconds if per_second is not None else None
        if price is None:
            raise VideoProviderError(
                f"No pricing configured for resolution {resolution!r} on {self.model_config.submit_path}"
            )
        return round(price, 4)

    @staticmethod
    def _diag(method: str, url: str) -> None:
        """Prints the exact outgoing request line - method and URL only,
        NEVER headers (the Authorization header carries the API key) - so
        this is always safe to leave on while debugging the live API."""
        print(f"[fal debug] {method} {url}")

    def _upload_reference_image(self, local_path: str) -> str:
        """fal.ai's documented 2-step upload: request a signed upload URL,
        PUT the file bytes to it, then use the returned public file URL as
        `image_url` in the generation request."""
        path = Path(local_path)
        content_type = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"

        initiate_url = f"{FAL_STORAGE_BASE}/storage/upload/initiate"
        self._diag("POST", initiate_url)
        initiate = self._client.post(
            initiate_url, headers=self._headers(), json={"content_type": content_type, "file_name": path.name}
        )
        if initiate.status_code >= 400:
            raise VideoProviderError(f"fal.ai upload initiate failed: {initiate.status_code} {initiate.text}")
        data = initiate.json()
        upload_url, file_url = data["upload_url"], data["file_url"]

        self._diag("PUT", upload_url)
        put_resp = self._client.put(upload_url, content=path.read_bytes(), headers={"Content-Type": content_type})
        if put_resp.status_code >= 400:
            raise VideoProviderError(f"fal.ai image upload failed: {put_resp.status_code}")
        return file_url

    def check_request(self, request: VideoGenerationRequest) -> None:
        """Refuse (never silently alter) a request this model can't take as asked."""
        cfg = self.model_config
        if not request.reference_image_path:
            raise VideoProviderError(f"{cfg.submit_path} is image-to-video; no start image was provided.")
        if request.end_image_path and not cfg.end_image_param_name:
            raise VideoProviderError(
                f"{cfg.submit_path} has no end-frame input; refusing rather than "
                "silently dropping the requested end image."
            )
        if cfg.requires_end_image and not request.end_image_path:
            raise VideoProviderError(f"{cfg.submit_path} needs both a first and a last frame.")
        if cfg.duration_param:
            seconds = request.duration_seconds
            if seconds != int(seconds) or (cfg.allowed_durations and int(seconds) not in cfg.allowed_durations):
                raise VideoProviderError(
                    f"{cfg.submit_path} takes durations {list(cfg.allowed_durations)} s, not {seconds:g} s."
                )
        shots = request.extra_params.get("multi_prompt")
        if shots is not None:
            if not cfg.supports_multi_prompt:
                raise VideoProviderError(f"{cfg.submit_path} has no multi_prompt (multi-shot) input.")
            if not shots or any(not (shot.get("prompt") or "").strip() for shot in shots):
                raise VideoProviderError("multi_prompt needs at least one shot, each with a prompt.")
            total = sum(int(shot["duration"]) for shot in shots)
            if total != request.duration_seconds:
                raise VideoProviderError(
                    f"multi_prompt shot durations add up to {total} s but the clip is {request.duration_seconds:g} s."
                )

    def build_payload(
        self, request: VideoGenerationRequest, image_url: str, end_image_url: str | None = None
    ) -> dict:
        """The exact JSON body submitted for `request`, given already-uploaded frame URLs. No network."""
        self.check_request(request)
        cfg = self.model_config
        payload: dict = {cfg.image_param_name: image_url}
        shots = request.extra_params.get("multi_prompt")
        if shots is not None:  # Kling v3: "Either prompt or multi_prompt must be provided, but not both."
            payload["multi_prompt"] = [{"prompt": shot["prompt"], "duration": str(int(shot["duration"]))}
                                       for shot in shots]
        else:
            payload["prompt"] = request.prompt
        if cfg.send_aspect_ratio:
            payload["aspect_ratio"] = request.aspect_ratio
        if end_image_url:
            payload[cfg.end_image_param_name] = end_image_url
        if cfg.supports_resolution_param:
            payload["resolution"] = self._resolution(request)
        if cfg.duration_param:
            payload[cfg.duration_param] = cfg.duration_format.format(int(request.duration_seconds))
        # Static fields specific to this model config (e.g. Kling's fixed
        # duration/negative_prompt, Veo's fixed duration) - set once in the
        # named config, not per-request.
        payload.update(cfg.extra_payload)

        # A small whitelist of documented knobs a caller can set via
        # extra_params, e.g. {"enable_prompt_expansion": False} to stop
        # fal.ai's own LLM-based prompt rewriting from introducing drift in
        # a multi-stage continuity chain, or {"seed": 123} for reproducible
        # generations. Anything else in extra_params (like "resolution",
        # already consumed above) is deliberately not passed through blind.
        for key in cfg.passthrough_params:
            if key in request.extra_params:
                payload[key] = request.extra_params[key]
        if cfg.audio_off_param:
            payload[cfg.audio_off_param] = False  # last, so nothing above can turn audio back on
        return payload

    def upload_image(self, local_path: str) -> str:
        return self._upload_reference_image(local_path)

    def submit_payload(self, payload: dict, estimated_cost_usd: float) -> SubmittedVideoJob:
        """Submit an exact, already-built payload (e.g. one a person reviewed in prepared.json)."""
        submit_url = f"{FAL_QUEUE_BASE}/{self.model_config.submit_path}"
        self._diag("POST", submit_url)
        resp = self._client.post(submit_url, headers=self._headers(), json=payload)
        if resp.status_code >= 400:
            raise VideoProviderError(f"fal.ai submit failed: {resp.status_code} {resp.text}")
        data = resp.json()
        return SubmittedVideoJob(
            provider_name=self.name,
            provider_job_id=data["request_id"],
            estimated_cost_usd=estimated_cost_usd,
            meta={"status_url": data.get("status_url"), "response_url": data.get("response_url")},
        )

    def submit_video_job(self, request: VideoGenerationRequest) -> SubmittedVideoJob:
        self.check_request(request)
        self._headers()  # fail on a missing key before any upload
        image_url = self._upload_reference_image(request.reference_image_path)
        end_image_url = self._upload_reference_image(request.end_image_path) if request.end_image_path else None
        payload = self.build_payload(request, image_url, end_image_url)
        return self.submit_payload(payload, self.estimate_cost(request))

    def get_job_status(self, provider_job_id: str, meta: dict | None = None) -> VideoJobStatusResult:
        # Prefer the status/result URLs fal.ai itself returned at submission
        # time (this is what fal's own official client does - see
        # fal_client.client.SyncRequestHandle, which stores and reuses
        # data["status_url"]/data["response_url"] rather than reconstructing
        # them). Only fall back to reconstructing from queue_app_id when we
        # don't have those - e.g. recovering a job whose original submission
        # response wasn't saved.
        meta = meta or {}
        status_url = meta.get("status_url") or (
            f"{FAL_QUEUE_BASE}/{self.model_config.queue_app_id}/requests/{provider_job_id}/status"
        )
        self._diag("GET", status_url)
        resp = self._client.get(status_url, headers=self._headers())
        if resp.status_code >= 400:
            raise VideoProviderError(f"fal.ai status check failed: {resp.status_code} {resp.text}")
        data = resp.json()
        status = data.get("status")

        if status in ("IN_QUEUE", "IN_PROGRESS"):
            # Keep fal's own finer-grained state so callers can show queued vs generating.
            return VideoJobStatusResult(status=ProviderJobState.PROCESSING, meta={"provider_status": status})

        if status == "COMPLETED":
            result_url = meta.get("response_url") or (
                f"{FAL_QUEUE_BASE}/{self.model_config.queue_app_id}/requests/{provider_job_id}"
            )
            self._diag("GET", result_url)
            result_resp = self._client.get(result_url, headers=self._headers())
            if result_resp.status_code >= 400:
                raise VideoProviderError(
                    f"fal.ai result fetch failed: {result_resp.status_code} {result_resp.text}"
                )
            result = result_resp.json()
            video_url = (result.get("video") or {}).get("url")
            if not video_url:
                raise VideoProviderError(f"fal.ai result had no video URL: {result}")
            return VideoJobStatusResult(status=ProviderJobState.COMPLETED, output_url=video_url)

        return VideoJobStatusResult(
            status=ProviderJobState.FAILED, error_message=f"fal.ai reported status {status!r}: {data}"
        )

    def download_result(self, provider_job_id: str, output_url: str, destination_path: str) -> str:
        self._diag("GET", output_url)
        resp = self._client.get(output_url)
        if resp.status_code >= 400:
            raise VideoProviderError(f"fal.ai clip download failed: {resp.status_code}")

        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return str(dest)
