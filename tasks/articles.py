"""
tasks/articles.py — Read Articles from the Bing Home Feed

Features:
  - Dynamically scales swipes and safe zones using device screen percentages
  - Tracks seen titles via a hashed set to avoid re-reading articles
  - Accepts count and duration as parameters (configured at the main menu level)
"""

import time

from config import (
    ARTICLE_RESOURCE_ID,
    ARTICLE_SCROLL_VIEW_ID,
    BACK_WAIT,
    MAX_FAILS,
    DEFAULT_ARTICLE_COUNT,
    DEFAULT_ARTICLE_DURATION,
)
from core.device import log, ensure_home_screen, go_back_to_home


# ── Feed navigation ────────────────────────────────────────────────

def scroll_to_articles(d):
    """Scrolls past top banner components into the primary article feed."""
    log("  Scrolling past header elements to feed...")
    d(resourceId=ARTICLE_SCROLL_VIEW_ID).scroll.forward(steps=40)
    time.sleep(1.5)


# ── Article reading core ───────────────────────────────────────────

def _get_title(el):
    """Extracts the text or accessibility content description from an element."""
    try:
        info = el.info
        return (info.get("text") or info.get("contentDescription") or "").strip()
    except Exception:
        return "(?)"


def read_articles(d, count, duration):
    """
    Processes unique unread news feed items sequentially.
    Scrolls down when no fresh articles are in the safe interaction zone.
    Returns the number of articles successfully read.
    """
    read_count  = 0
    fail_count  = 0
    seen_titles = set()

    # Dynamic geometry — scales to any device resolution
    display_width  = d.info.get("displayWidth",  900)
    display_height = d.info.get("displayHeight", 1600)

    swipe_x       = int(display_width  * 0.50)   # horizontal center
    swipe_start_y = int(display_height * 0.75)   # 75% down
    swipe_end_y   = int(display_height * 0.375)  # 37.5% down

    safe_zone_top    = int(display_height * 0.15)  # 15% top margin
    safe_zone_bottom = int(display_height * 0.85)  # 85% bottom margin

    while read_count < count:
        articles = d(resourceId=ARTICLE_RESOURCE_ID)

        if not articles.exists:
            fail_count += 1
            log(f"  [!] No feed items found (miss {fail_count}/{MAX_FAILS})")
            if fail_count >= MAX_FAILS:
                log("  [STOP] Too many consecutive misses — aborting.")
                break
            d.swipe(swipe_x, swipe_start_y, swipe_x, swipe_end_y, 0.35)
            time.sleep(1.5)
            continue

        fail_count = 0
        clicked_this_loop = False

        for el in articles:
            title = _get_title(el)

            if title == "(?)" or title in seen_titles:
                continue

            bounds   = el.info.get("bounds", {})
            center_y = (bounds.get("top", 0) + bounds.get("bottom", 0)) / 2

            if center_y < safe_zone_top or center_y > safe_zone_bottom:
                continue

            label = title[:70] + "…" if len(title) > 70 else title
            log(f"  [{read_count+1}/{count}] {label}")

            try:
                el.click()
                clicked_this_loop = True
                seen_titles.add(title)
                break
            except Exception as e:
                log(f"  [!] Tap failed: {e} — skipping.")
                continue

        if not clicked_this_loop:
            log("  No fresh articles in safe zone — scrolling down...")
            d.swipe(swipe_x, swipe_start_y, swipe_x, swipe_end_y, 0.35)
            time.sleep(1.5)
            continue

        log(f"  Reading for {duration}s...")
        time.sleep(duration)

        d.press("back")
        time.sleep(BACK_WAIT)
        read_count += 1

    return read_count

# ── Task entry point ───────────────────────────────────────────────

def run(d, articles_limit=DEFAULT_ARTICLE_COUNT, read_duration=DEFAULT_ARTICLE_DURATION):
    """
    Execute the Read Articles task on an already-connected device.
    Assumes Bing is running and the home screen is confirmed before calling.

    If articles_limit or read_duration are not provided, the user is prompted.
    Returns a result dict with keys: read_count, articles_limit.
    """
    # if articles_limit is None or read_duration is None:
    #     articles_limit, read_duration = prompt_config()

    log(f"\nStarting article read — Target: {articles_limit} articles at {read_duration}s each.")

    # Ensure we are on the home screen before scrolling to the feed
    if not ensure_home_screen(d):
        log("[ABORT] Could not confirm home screen before reading articles.")
        return None

    scroll_to_articles(d)
    actual_reads = read_articles(d, articles_limit, read_duration)

    # Return to Bing home screen after reading
    log("\nReturning to home screen...")
    go_back_to_home(d)

    return {
        "read_count":     actual_reads,
        "articles_limit": articles_limit,
    }


def print_report(result):
    """Print the Read Articles summary report."""
    if result is None:
        print("\n  [!] Read Articles task did not complete.")
        return

    read_count     = result["read_count"]
    articles_limit = result["articles_limit"]
    status = "SUCCESS ✓" if read_count == articles_limit else "PARTIAL / INCOMPLETE"

    print()
    print("=" * 52)
    print(f"  Articles Read : {read_count} / {articles_limit}")
    print(f"  Status        : {status}")
    print("=" * 52)
