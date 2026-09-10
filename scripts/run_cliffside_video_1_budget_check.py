#!/usr/bin/env python3
"""CLIFFSIDE VIDEO #1 - BUDGET CHECK.

Pure local read of data/cliffside_video_1/manifest.json. NO API calls, NO
FAL_API_KEY needed, NO spend of any kind. Run this before any paid stage
to see exactly how much of the hard budget cap is already spent and how
much remains, without having to add the numbers up by hand.

The cap defaults to $5.00 (the remaining-budget authorization for
finishing Cliffside Video #1's Part 2 generation). Pass a different
number as the one CLI argument to check against a different cap.

Usage (from the repo root - no FAL_API_KEY needed):
    python -m scripts.run_cliffside_video_1_budget_check
    python -m scripts.run_cliffside_video_1_budget_check 3.00
"""
import json
import sys

from scripts.run_cliffside_video_1_rough_assembly import MANIFEST_PATH

DEFAULT_CAP_USD = 5.00

# manifest key -> human label, in spend order.
SPEND_KEYS = [
    ("decking_complete_edit", "Decking-completion edit"),
    ("framing", "Framing (Wan)"),
    ("framing_complete_edit", "Framing-completion edit"),
    ("glass", "Glass/Door (Wan)"),
    ("exterior_complete_edit", "Exterior-completion edit"),
    ("reveal", "Reveal (Wan)"),
]


def main() -> None:
    cap = float(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CAP_USD

    if not MANIFEST_PATH.exists():
        print(f"No manifest yet at {MANIFEST_PATH} - nothing spent so far.")
        print(f"Full budget available: ${cap:.2f}")
        return

    manifest = json.loads(MANIFEST_PATH.read_text())

    print("=" * 60)
    print("CLIFFSIDE VIDEO #1 - PART 2 BUDGET CHECK (local, no API calls)")
    print("=" * 60)

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
    print("-" * 60)
    print(f"Cap:       ${cap:.2f}")
    print(f"Spent:     ${spent:.2f}")
    print(f"Remaining: ${remaining:.2f}")
    if remaining < 0:
        print("\nWARNING: spend already exceeds the cap - stop and review before any further call.")


if __name__ == "__main__":
    main()
