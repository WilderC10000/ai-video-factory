#!/usr/bin/env python3
"""FORMA VIDEO #2 - BUDGET CHECK.

Pure local read of data/alpine_video_2/manifest.json. NO API calls, NO
FAL_API_KEY needed, NO spend of any kind. Run this any time to see exactly
how much of the $6.50 hard budget cap is already spent and how much
remains, broken down stage by stage, without adding the numbers up by hand.

Usage (from the repo root - no FAL_API_KEY needed):
    python -m scripts.run_alpine_video_2_budget_check
    python -m scripts.run_alpine_video_2_budget_check 5.00
"""
import sys

from scripts.run_alpine_video_2_common import BUDGET_CAP_USD, MANIFEST_PATH, load_manifest

# manifest key -> human label, in spend order.
SPEND_KEYS = [
    ("site_reference", "Site reference image (Nano Banana Pro Generate)"),
    ("shot1", "Shot 1 - Opening + Site Prep (Wan)"),
    ("shot2", "Shot 2 - Base + Floor (Wan)"),
    ("edit1_base_floor_complete", "Edit 1 - Base/Floor Complete"),
    ("shot3", "Shot 3 - Floorboards (Wan)"),
    ("edit2_floor_complete", "Edit 2 - Floor Complete"),
    ("shot4", "Shot 4 - A-Frame Ribs [HERO] (Wan)"),
    ("edit3_framing_complete", "Edit 3 - Framing Complete"),
    ("shot5", "Shot 5 - Roof + Cladding (Wan)"),
    ("edit4_roof_complete", "Edit 4 - Roof/Cladding Complete"),
    ("shot6", "Shot 6 - Glass Facade (Wan)"),
    ("edit5_glass_complete", "Edit 5 - Glass Complete + Interior Move"),
    ("shot7", "Shot 7 - Interior Design (Wan)"),
    ("edit6_exterior_reveal_viewpoint", "Edit 6 - Exterior Reveal Viewpoint"),
    ("shot8", "Shot 8 - Final Reveal (Wan)"),
]


def main() -> None:
    cap = float(sys.argv[1]) if len(sys.argv) > 1 else BUDGET_CAP_USD

    if not MANIFEST_PATH.exists():
        print(f"No manifest yet at {MANIFEST_PATH} - nothing spent so far.")
        print(f"Full budget available: ${cap:.2f}")
        return

    manifest = load_manifest()

    print("=" * 70)
    print("FORMA VIDEO #2 - BUDGET CHECK (local, no API calls)")
    print("=" * 70)

    spent = 0.0
    for key, label in SPEND_KEYS:
        entry = manifest.get(key)
        cost = entry.get("actual_cost_usd") if entry else None
        if cost is None:
            print(f"  [ not run  ] {label}")
            continue
        spent += cost
        print(f"  [${cost:>5.2f}] {label}")

    remaining = cap - spent
    print("-" * 70)
    print(f"Cap:       ${cap:.2f}")
    print(f"Spent:     ${spent:.2f}")
    print(f"Remaining: ${remaining:.2f}")
    if remaining < 0:
        print("\nWARNING: spend already exceeds the cap - stop and review before any further call.")


if __name__ == "__main__":
    main()
