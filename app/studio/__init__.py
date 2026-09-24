"""FORMA Virtual Studio - a visual control room over real FORMA production state.

Everything here is additive and isolated from the video-generation pipeline:
studio_* tables are a read-only mirror of the per-project manifests the
pipeline scripts write, never a source of truth those scripts read back.
"""
