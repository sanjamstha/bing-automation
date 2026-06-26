"""
tasks/articles.py — Read Articles from the Bing Home Feed

Flow:
  Open Rewards page → Scroll to "Read to earn" row → Check done/not-done + parse
  daily point limit → Return to home screen → Scroll into article feed → Read articles

Read to Earn check:
  - Row clickable + Y parsed → derive article target: (Y // 3) + random bonus
  - Row not clickable (already done today) → skip article reading entirely
  - Row not found / parse failed (exhausted) → fall back to ARTICLE_COUNT_MIN/MAX range

Features:
  - Dynamically scales swipes and safe zones using device screen percentages
  - Tracks seen titles via a hashed set to avoid re-reading articles
"""

import time
import random

from config import (
    BING_PACKAGE,
    HOME_ACTIVITY,
    ARTICLE_RESOURCE_ID,
    ARTICLE_SCROLL_VIEW_ID,
    BACK_WAIT,
    MAX_FAILS,
    MAX_SCROLL_ATTEMPTS,
    ARTICLE_COUNT_MIN,
    ARTICLE_COUNT_MAX,
    ARTICLE_DURATION_MIN,
    ARTICLE_DURATION_MAX,
    READ_TO_EARN_DESC,
    ARTICLE_BONUS_MIN,
    ARTICLE_BONUS_MAX,
)
from core.device import log, ensure_home_screen, go_back_to_home, launch_bing, dismiss_popup
from tasks.daily import open_rewards_page, wait_for_rewards_page


# ── Feed navigation ────────────────────────────────────────────────

def scroll_to_articles(d):
    """Scrolls past top banner components into the primary article feed."""
    log("  Scrolling past header elements to feed...")
    d(resourceId=ARTICLE_SCROLL_VIEW_ID).scroll.forward(steps=40)
    time.sleep(1.5)


# ── Read to Earn check ─────────────────────────────────────────────

def _parse_xy_from_desc(desc):
    """
    Extracts X (points already earned) and Y (daily limit) from the 'Read to earn' content-desc.
    Expected format: "Read to earn, , 12 out of 30 points earned"
    Returns (x_value, y_value) as ints, or (None, None) if parsing fails.
    """
    try:
        before, after = desc.split("out of ")  # before = "...12 ", after = "30 points earned"
        x_str = before.strip().split(" ")[-1]  # last token before "out of" = "12"
        y_str = after.split(" points")[0]       # "30"
        return int(x_str.strip()), int(y_str.strip())
    except (IndexError, ValueError):
        return None, None


def _get_geometry(d):
    w = d.info.get("displayWidth",  900)
    h = d.info.get("displayHeight", 1600)
    return {
        "cx":          w // 2,
        "swipe_start": int(h * 0.70),
        "swipe_end":   int(h * 0.35),
        "safe_top":    int(h * 0.12),
        "safe_bottom": int(h * 0.92),
    }


def _scroll_down_one(d):
    """Swipe up one step to scroll the rewards page down."""
    geo = _get_geometry(d)
    try:
        d.swipe(geo["cx"], geo["swipe_start"], geo["cx"], geo["swipe_end"], 0.35)
    except Exception as e:
        log(f"  [WARN] Swipe failed: {e.__class__.__name__} — skipping scroll.")
    time.sleep(1.8)


def _in_safe_zone(bounds, geo):
    """Returns True if the element's vertical center is within the safe interaction zone."""
    cy = (bounds.get("top", 0) + bounds.get("bottom", 0)) / 2
    return geo["safe_top"] < cy < geo["safe_bottom"]


def _check_and_parse_read_row(row):
    """
    Called when the 'Read to earn' row is confirmed visible and in safe zone.
    Checks clickability (done-for-day detection) and parses Y from content-desc.
    Returns (True, y_value) on success, (False, 0) otherwise.
    """
    info = row.info

    # Done-for-day detection — completed row becomes non-clickable
    if not info.get("clickable", False):
        log("  'Read to earn' is not clickable — already completed today ✓")
        return False, 0

    desc = info.get("contentDescription", "")
    x_value, y_value = _parse_xy_from_desc(desc)

    if x_value is None or y_value is None:
        log(f"  [FAIL] Could not parse read limit from content-desc: '{desc}'")
        return False, 0

    remaining = y_value - x_value
    log(f"  Parsed: {x_value}/{y_value} pts earned — {remaining} pts remaining")
    return True, remaining


def _scroll_to_read_earn(d):
    """
    Scrolls down the rewards page until the 'Read to earn' row is visible
    AND within the safe interaction zone.

    On each iteration checks two selectors:
      1. descriptionContains — active row (not yet completed)
      2. textContains        — completed row (clickable=false, text-only node)

    Once the active row is found in safe zone, delegates to _check_and_parse_read_row.

    Final-scroll last-chance: after exhausting MAX_SCROLL_ATTEMPTS, does one
    final scan before returning exhausted.

    Returns (True,  y_value, "ok")        — row found, parsed, ready to read
    Returns (False, 0,       "done")      — already completed today
    Returns (False, 0,       "exhausted") — scroll attempts exhausted, use fallback count
    """
    log("  Scrolling to find 'Read to earn' section...")
    geo = _get_geometry(d)

    for attempt in range(1, MAX_SCROLL_ATTEMPTS + 1):
        # Check active row (not yet completed)
        row = d(descriptionContains=READ_TO_EARN_DESC)
        if row.exists:
            bounds = row.info.get("bounds", {})
            if _in_safe_zone(bounds, geo):
                log("  'Read to earn' row visible and in safe zone ✓")
                found, y = _check_and_parse_read_row(row)
                return (found, y, "ok") if found else (False, 0, "done")
            else:
                log("  Row found but outside safe zone — scrolling into view...")
        else:
            # Check completed row (text-only node, no content-desc)
            done_row = d(textContains=READ_TO_EARN_DESC)
            if done_row.exists and not done_row.info.get("clickable", True):
                log("  'Read to earn' completed row found — already done today ✓")
                return False, 0, "done"
            log(f"  Not visible yet — scrolling (attempt {attempt}/{MAX_SCROLL_ATTEMPTS})...")

        _scroll_down_one(d)

    # Final-scroll last-chance check
    row = d(descriptionContains=READ_TO_EARN_DESC)
    if row.exists:
        bounds = row.info.get("bounds", {})
        if _in_safe_zone(bounds, geo):
            log("  'Read to earn' appeared on final scroll ✓")
            found, y = _check_and_parse_read_row(row)
            return (found, y, "ok") if found else (False, 0, "done")

    # Also check completed state on final scan
    done_row = d(textContains=READ_TO_EARN_DESC)
    if done_row.exists and not done_row.info.get("clickable", True):
        log("  'Read to earn' completed row found on final scan — already done today ✓")
        return False, 0, "done"

    log("  [FAIL] 'Read to earn' not found after max scroll attempts.")
    return False, 0, "exhausted"


def _check_read_to_earn(d):
    """
    Opens the Rewards page, scrolls to 'Read to earn', and returns the
    article target derived from the daily point limit.

    Returns (True,  y_value) — row active, proceed with dynamic count
    Returns (False, 0)       — already done today, skip article reading
    Returns (None,  0)       — rewards page unreachable or row not found (use fallback)

    Leaves the device on the Rewards page — caller must navigate back to home.
    """
    # Dismiss any popup before opening the rewards page
    log("  [READ TO EARN] Checking for popups...")
    dismiss_popup(d)

    log("  [READ TO EARN] Opening Rewards page...")
    if not open_rewards_page(d):
        log("  [READ TO EARN] Could not open Rewards page — will use fallback count.")
        return None, 0

    log("  [READ TO EARN] Waiting for Rewards page to load...")
    if not wait_for_rewards_page(d):
        log("  [READ TO EARN] Rewards page did not load — will use fallback count.")
        return None, 0

    found, y_value, status = _scroll_to_read_earn(d)

    if status == "done":
        return False, 0       # already completed today — skip articles

    if status == "exhausted":
        return None, 0        # couldn't find row — caller uses fallback count

    # status == "ok"
    return True, y_value


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
            try:
                d.swipe(swipe_x, swipe_start_y, swipe_x, swipe_end_y, 0.35)
            except Exception as e:
                log(f"  [WARN] Swipe failed: {e.__class__.__name__} — skipping scroll.")
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
            try:
                d.swipe(swipe_x, swipe_start_y, swipe_x, swipe_end_y, 0.35)
            except Exception as e:
                log(f"  [WARN] Swipe failed: {e.__class__.__name__} — skipping scroll.")
            time.sleep(1.5)
            continue

        actual_duration = random.uniform(duration[0], duration[1])
        log(f"  Reading for {actual_duration:.1f}s...")
        time.sleep(actual_duration)

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

def run(d):
    """
    Execute the Read Articles task on an already-connected device.
    Assumes Bing is running and the home screen is confirmed before calling.

    Flow:
      [1/3] Open Rewards page → check 'Read to earn' row → derive article count
      [2/3] Return to home screen → scroll into article feed
      [3/3] Run article reading loop

    Article count derivation:
      - Row active + Y parsed → (Y // 3) + random bonus (ARTICLE_BONUS_MIN–MAX)
      - Row already done today → skip entirely, return read_count=0, articles_limit=0
      - Row not found / rewards page failed → fallback to ARTICLE_COUNT_MIN/MAX range

    Returns a result dict with keys: read_count, articles_limit.
    Returns None only on hard abort (home screen unreachable before reading).
    """
    read_duration = (ARTICLE_DURATION_MIN, ARTICLE_DURATION_MAX)

    # ── [1/3] Read to Earn check ───────────────────────────────────
    log(" [1/3] Checking 'Read to earn' on Rewards page...")
    found, y_value = _check_read_to_earn(d)

    if found is False:
        # Confirmed done today — skip article reading entirely
        log("  'Read to earn' already completed today — skipping article read.")
        go_back_to_home(d)
        return {"read_count": 0, "articles_limit": 0}

    if found is None:
        # Rewards page unreachable or row not found — use fallback count
        articles_limit = random.randint(ARTICLE_COUNT_MIN, ARTICLE_COUNT_MAX)
        log(f"  Read to Earn check inconclusive — using fallback count: {articles_limit} articles.")
    else:
        # Row active — derive count from daily point limit + bonus
        articles_limit = (y_value // 3) + random.randint(ARTICLE_BONUS_MIN, ARTICLE_BONUS_MAX)
        log(f"  Target: {y_value} remaining pts ÷ 3 = {y_value // 3} base + bonus = {articles_limit} total")

    log(f" Starting article read — Target: {articles_limit} articles, "
        f"{ARTICLE_DURATION_MIN}–{ARTICLE_DURATION_MAX}s each.")

    # ── [2/3] Return to home screen ────────────────────────────────
    # _check_read_to_earn() leaves us on the Rewards page — navigate back first.
    log(" [2/3] Returning to home screen before article feed...")
    go_back_to_home(d)

    if not ensure_home_screen(d):
        log("[ABORT] Could not confirm home screen before reading articles.")
        return None

    scroll_to_articles(d)

    # ── [3/3] Article reading loop ─────────────────────────────────
    log(f" [3/3] Reading articles...")
    actual_reads = read_articles(d, articles_limit, read_duration)

    # Return to Bing home screen after reading
    log(" Returning to home screen...")
    go_back_to_home(d)

    return {
        "read_count":     actual_reads,
        "articles_limit": articles_limit,
    }


def print_report(result):
    """Print the Read Articles summary report."""
    if result is None:
        print("   [!] Read Articles task did not complete.")
        return

    read_count     = result["read_count"]
    articles_limit = result["articles_limit"]
    status = "SUCCESS ✓" if read_count == articles_limit else "PARTIAL / INCOMPLETE"

    print()
    print("=" * 52)
    print(f"  Articles Read : {read_count} / {articles_limit}")
    print(f"  Status        : {status}")
    print("=" * 52)