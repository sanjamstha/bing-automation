"""
tasks/articles.py — Read Articles from the Bing Home Feed

Features:
  - Dynamically scales swipes and safe zones using device screen percentages
  - Tracks seen titles via a hashed set to avoid re-reading articles
  - Accepts count and duration as parameters (configured at the main menu level)
"""

import time

from config import (
    BING_PACKAGE,
    HOME_ACTIVITY,
    ARTICLE_RESOURCE_ID,
    ARTICLE_SCROLL_VIEW_ID,
    BACK_WAIT,
    MAX_FAILS,
    DEFAULT_ARTICLE_COUNT,
    DEFAULT_ARTICLE_DURATION,
)
from core.device import log, ensure_home_screen, go_back_to_home, launch_bing


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


def _article_loop(d, count, duration, seen_titles, start_count=0):
    """
    Inner article reading loop. Separated so it can be called for both the
    initial pass and the single recovery pass without duplicating code.
    Returns the number of articles read during this pass.
    """
    read_count  = start_count
    fail_count  = 0

    display_width  = d.info.get("displayWidth",  900)
    display_height = d.info.get("displayHeight", 1600)

    swipe_x       = int(display_width  * 0.50)
    swipe_start_y = int(display_height * 0.75)
    swipe_end_y   = int(display_height * 0.375)

    safe_zone_top    = int(display_height * 0.15)
    safe_zone_bottom = int(display_height * 0.85)

    while read_count < count:
        articles = d(resourceId=ARTICLE_RESOURCE_ID)

        if not articles.exists:
            fail_count += 1
            log(f"  [!] No feed items found (miss {fail_count}/{MAX_FAILS})")
            if fail_count >= MAX_FAILS:
                log("  [STOP] Too many consecutive misses — stopping this pass.")
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


def _on_home_screen(d):
    """Returns True if the current activity is the Bing home screen."""
    activity = d.app_current().get("activity", "")
    return HOME_ACTIVITY in activity


def _recover_via_relaunch(d, count, duration, seen_titles, read_count):
    """
    Branch A recovery: cold relaunch → home screen → scroll to feed → retry loop.
    Returns updated read_count.
    """
    if launch_bing(d) and ensure_home_screen(d):
        log("  [RECOVER] Back on home screen — scrolling to feed and continuing...")
        scroll_to_articles(d)
        read_count = _article_loop(d, count, duration, seen_titles, start_count=read_count)
    else:
        log("  [RECOVER] Relaunch failed — stopping article read.")
    return read_count


def read_articles(d, count, duration):
    """
    Processes unique unread news feed items sequentially.
    Scrolls down when no fresh articles are in the safe interaction zone.

    Recovery: when MAX_FAILS is exhausted mid-read, checks device location
    using a 3-branch strategy mirroring daily.py's collect_cards():

      BRANCH A — Park (outside Bing entirely):
        → cold relaunch → ensure_home_screen() → scroll_to_articles()
        → retry loop once.

      BRANCH B — Wrong room (Bing is active package but not on HOME_ACTIVITY):
        → go_back_to_home() → ensure_home_screen() → scroll_to_articles()
        → retry loop once.
        → if ensure_home_screen() fails → fall back to Branch A (full relaunch).

      BRANCH C — Right room (on HOME_ACTIVITY, feed just dried up):
        → exit cleanly, articles genuinely unavailable.

    seen_titles is preserved across all passes so already-read articles are
    never repeated. Max one recovery — cannot loop infinitely.

    Returns the total number of articles successfully read.
    """
    seen_titles = set()

    # First pass
    read_count = _article_loop(d, count, duration, seen_titles, start_count=0)

    if read_count >= count:
        return read_count

    # ── Recovery: location check ───────────────────────────────────
    package = d.app_current().get("package", "")

    # BRANCH C — right room, feed just dried up
    if BING_PACKAGE in package and _on_home_screen(d):
        log("  Feed genuinely unavailable (internet issue or Bing not serving articles).")
        return read_count

    # BRANCH B — inside Bing but wrong room
    if BING_PACKAGE in package:
        log("  [RECOVER] Wrong room inside Bing — navigating back to home screen...")
        go_back_to_home(d)
        if ensure_home_screen(d):
            log("  [RECOVER] Back on home screen — scrolling to feed and continuing...")
            scroll_to_articles(d)
            read_count = _article_loop(d, count, duration, seen_titles, start_count=read_count)
            return read_count
        # Home screen unreachable via back — fall through to full relaunch
        log("  [RECOVER] Could not reach home screen via back — attempting full relaunch...")

    # BRANCH A — outside Bing entirely, or Branch B fallback
    else:
        log(f"  [RECOVER] Outside Bing (current: {package or 'unknown'}) — relaunching...")

    read_count = _recover_via_relaunch(d, count, duration, seen_titles, read_count)
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