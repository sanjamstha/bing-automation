"""
tasks/points.py — Current Points Balance Reader

Reads the "X,XXX pts" balance shown near the top of the Rewards page. Assumes the Rewards page is already open and loaded — this module does no navigation of its own.

The points number and the "pts" label are two separate, attribute-less TextView nodes (no resource-id, no content-desc) sitting side by side. The "pts" label text is the one stable anchor; the number is found by scanning sibling TextViews for one that sits at the same vertical center and just to the label's left.

This is intentionally read-only and best-effort: any failure (label not found, ambiguous match, unparsable text, unexpected UI exception) returns None rather than raising, so a balance-reading hiccup never takes down the calling task.
"""

import re
from config import POINTS_LABEL_TEXT
from core.device import log


def get_current_points(d):
    """
    Returns the current points balance as an int, or None if it could not be reliably determined.
    """
    try:
        label_nodes = d(text=POINTS_LABEL_TEXT)

        count = len(label_nodes)
        if count == 0:
            log(f"  [POINTS] Label '{POINTS_LABEL_TEXT}' not found — cannot read balance.")
            return None
        if count > 1:
            log(f"  [POINTS] Label '{POINTS_LABEL_TEXT}' matched {count} nodes "
                f"(ambiguous) — skipping read.")
            return None

        label_info   = label_nodes.info
        label_bounds = label_info.get("bounds", {})
        label_top    = label_bounds.get("top", 0)
        label_bottom = label_bounds.get("bottom", 0)
        label_left   = label_bounds.get("left", 0)
        label_cy     = (label_top + label_bottom) / 2
        label_height = max(label_bottom - label_top, 1)

        # Tolerance scales with the label's own height so this adapts
        # across different screen resolutions/DPIs rather than relying
        # on a fixed pixel value tuned to one device.
        vertical_tolerance = max(20, label_height * 0.5)

        candidates = d(className="android.widget.TextView")
        if not candidates.exists:
            log("  [POINTS] No TextView nodes found on screen — cannot read balance.")
            return None

        best_text     = None
        best_distance = None

        for node in candidates:
            try:
                info = node.info
                text = (info.get("text") or "").strip()
                if not text or text == POINTS_LABEL_TEXT:
                    continue

                bounds = info.get("bounds", {})
                top    = bounds.get("top", 0)
                bottom = bounds.get("bottom", 0)
                right  = bounds.get("right", 0)
                cy     = (top + bottom) / 2

                vertical_match   = abs(cy - label_cy) < vertical_tolerance
                horizontal_match = right <= label_left + 5  # small tolerance

                if vertical_match and horizontal_match:
                    distance = label_left - right
                    if best_distance is None or distance < best_distance:
                        best_text     = text
                        best_distance = distance
            except Exception:
                # A single bad node shouldn't abort the whole scan.
                continue

        if best_text is None:
            log("  [POINTS] Could not locate a number positioned left of the "
                f"'{POINTS_LABEL_TEXT}' label — cannot read balance.")
            return None

        cleaned = best_text.replace(",", "").strip()
        if not re.fullmatch(r"\d+", cleaned):
            log(f"  [POINTS] Matched text '{best_text}' is not a clean integer "
                f"(cleaned='{cleaned}') — cannot read balance.")
            return None

        points = int(cleaned)
        log(f"  [POINTS] Current balance: {points:,} pts")
        return points

    except Exception as e:
        log(f"  [POINTS] Unexpected error while reading balance: "
            f"{e.__class__.__name__}: {e}")
        return None