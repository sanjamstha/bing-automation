"""
tasks/search.py — Search to Earn

Flow:
  Start on Bing homepage → Open Rewards page → Scroll until "Search to earn" is visible
  → Tap "Search to earn" → Wait for search overlay → Type query → Hold results → Back
  → Wait between searches → Repeat for SEARCH_COUNT total searches → Return to home screen

Recovery: when any step in the search loop fails, a unified location check runs a
3-branch strategy before retrying once:

  BRANCH A — Outside Bing entirely (or Branch B fallback):
    → launch_bing() → ensure_home_screen() → dismiss_popup()
    → _navigate_to_rewards() → _scroll_to_search_earn() → retry loop once.

  BRANCH B — Inside Bing but wrong room (not on rewards page or search overlay):
    → go_back_to_home() → ensure_home_screen() → _navigate_to_rewards()
    → _scroll_to_search_earn() → retry loop once.
    → if that fails → fall through to Branch A.

  BRANCH C — Right room (rewards page landmarks visible):
    → "Search to earn" genuinely unavailable → exit cleanly.

  OVERLAY — Search overlay is still open when recovery fires:
    → press action_back to close overlay → fall through to rewards page check.

Max one recovery per run — cannot loop infinitely.
"""

import time
import random

from config import (
    BING_PACKAGE,
    SEARCH_OVERLAY_ID,
    SEARCH_INPUT_ID,
    SEARCH_ACTION_BACK,
    SEARCH_TO_EARN_DESC,
    SEARCH_HOLD_MIN,
    SEARCH_HOLD_MAX,
    SEARCH_WAIT_MIN,
    SEARCH_WAIT_MAX,
    SEARCH_BONUS_MIN,
    SEARCH_BONUS_MAX,
    MAX_SCROLL_ATTEMPTS,
    OVERLAY_TIMEOUT,
)
from core.device import (
    log,
    go_back_to_home,
    launch_bing,
    ensure_home_screen,
    dismiss_popup,
)
from tasks.daily import open_rewards_page, wait_for_rewards_page
from tasks.queries import get_queries


# ── Geometry helpers ───────────────────────────────────────────────

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
    """Swipe up one step to scroll the rewards page down. Mirrors daily.py logic."""
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


# ── Rewards page helpers ───────────────────────────────────────────

def _on_rewards_page(d):
    """Returns True if any known Rewards page landmark is currently visible."""
    return (
        d(text="Today's points").exists
        or d(text="Daily set").exists
        or d(text="Streaks").exists
        or d(text="More activities").exists
        or d(text="Daily activities").exists
    )


def _navigate_to_rewards(d):
    """
    Attempts to open and confirm the Rewards page from the Bing home screen.
    Returns True if the Rewards page loaded successfully, False otherwise.
    """
    if not open_rewards_page(d):
        log("  [RECOVER] Rewards card not found on home screen.")
        return False
    if not wait_for_rewards_page(d):
        log("  [RECOVER] Rewards page did not load after tapping card.")
        return False
    return True


# ── Search overlay helpers ─────────────────────────────────────────

def _on_search_overlay(d):
    """Returns True if the search overlay is currently open."""
    return (
        d(resourceId=SEARCH_OVERLAY_ID).exists
        or d(resourceId=SEARCH_INPUT_ID).exists
    )


def _close_search_overlay(d):
    """
    Closes the search overlay via the action_back button if present,
    falls back to system back key. Waits for overlay to dismiss.
    """
    log("  [RECOVER] Closing search overlay before recovery...")
    btn = d(resourceId=SEARCH_ACTION_BACK)
    if btn.exists:
        btn.click()
    else:
        d.press("back")
    time.sleep(2.5)


# ── Search to earn section ─────────────────────────────────────────

def _parse_y_from_desc(desc):
    """
    Extracts the Y (daily limit) value from the 'Search to earn' content-desc.
    Expected format: "Search to earn, , 6 out of 60 points earned"
    Returns the integer Y, or None if parsing fails.
    """
    try:
        after = desc.split("out of ")[1]   # "60 points earned"
        y_str = after.split(" points")[0]  # "60"
        return int(y_str.strip())
    except (IndexError, ValueError):
        return None


def _scroll_to_search_earn(d):
    """
    Scrolls down the rewards page until the 'Search to earn' row is visible
    AND within the safe interaction zone.

    On each iteration checks two selectors:
      1. descriptionContains — active row (not yet completed)
      2. textContains        — completed row (clickable=false, text-only node)

    Once the active row is found in safe zone, delegates to _check_and_parse_row.

    Final-scroll last-chance: after exhausting MAX_SCROLL_ATTEMPTS, does one
    final scan before returning exhausted.

    Returns (True,  y_value, "ok")         — row found, parsed, ready to search
    Returns (False, 0,       "done")       — already completed today
    Returns (False, 0,       "exhausted")  — scroll attempts exhausted, try recovery
    """
    log("  Scrolling to find 'Search to earn' section...")
    geo = _get_geometry(d)

    for attempt in range(1, MAX_SCROLL_ATTEMPTS + 1):
        # Check active row (not yet completed)
        row = d(descriptionContains=SEARCH_TO_EARN_DESC)
        if row.exists:
            bounds = row.info.get("bounds", {})
            if _in_safe_zone(bounds, geo):
                log("  'Search to earn' row visible and in safe zone ✓")
                found, y = _check_and_parse_row(row)
                return (found, y, "ok") if found else (False, 0, "done")
            else:
                log("  Row found but outside safe zone — scrolling into view...")
        else:
            # Check completed row (text-only node, no content-desc)
            done_row = d(textContains=SEARCH_TO_EARN_DESC)
            if done_row.exists and not done_row.info.get("clickable", True):
                log("  'Search to earn' completed row found — already done today ✓")
                return False, 0, "done"
            log(f"  Not visible yet — scrolling (attempt {attempt}/{MAX_SCROLL_ATTEMPTS})...")

        _scroll_down_one(d)

    # Final-scroll last-chance check
    row = d(descriptionContains=SEARCH_TO_EARN_DESC)
    if row.exists:
        bounds = row.info.get("bounds", {})
        if _in_safe_zone(bounds, geo):
            log("  'Search to earn' appeared on final scroll ✓")
            found, y = _check_and_parse_row(row)
            return (found, y, "ok") if found else (False, 0, "done")

    # Also check completed state on final scan
    done_row = d(textContains=SEARCH_TO_EARN_DESC)
    if done_row.exists and not done_row.info.get("clickable", True):
        log("  'Search to earn' completed row found on final scan — already done today ✓")
        return False, 0, "done"

    log("  [FAIL] 'Search to earn' not found after max scroll attempts.")
    return False, 0, "exhausted"


def _check_and_parse_row(row):
    """
    Called when the 'Search to earn' row is confirmed visible and in safe zone.
    Checks clickability (done-for-day detection) and parses Y from content-desc.
    Returns (True, y_value) on success, (False, 0) otherwise.
    """
    info = row.info

    # Done-for-day detection — completed row becomes non-clickable
    if not info.get("clickable", False):
        log("  'Search to earn' is not clickable — already completed today ✓")
        return False, 0

    desc = info.get("contentDescription", "")
    y_value = _parse_y_from_desc(desc)

    if y_value is None:
        log(f"  [FAIL] Could not parse search limit from content-desc: '{desc}'")
        return False, 0

    log(f"  Parsed daily search limit: {y_value} points")
    return True, y_value


def _tap_search_to_earn(d):
    """
    Taps the 'Search to earn' row to open the search overlay.
    Returns False if the row is not found.
    """
    row = d(descriptionContains=SEARCH_TO_EARN_DESC)
    if not row.exists:
        log("  [FAIL] 'Search to earn' row not found — cannot tap.")
        return False
    log("  Tapping 'Search to earn'...")
    row.click()
    return True


# ── Search overlay ─────────────────────────────────────────────────

def _wait_for_search_overlay(d):
    """
    Polls until the search overlay input is visible.
    Returns True if confirmed open within OVERLAY_TIMEOUT, False otherwise.
    """
    log(f"  Waiting for search overlay (up to {OVERLAY_TIMEOUT}s)...")
    deadline = time.time() + OVERLAY_TIMEOUT
    while time.time() < deadline:
        if d(resourceId=SEARCH_OVERLAY_ID).exists:
            log("  Search overlay open ✓")
            return True
        time.sleep(0.8)
    log("  [FAIL] Search overlay did not open within timeout.")
    return False


def _do_single_search(d, query):
    """
    Types query into the search input, submits, holds results for a randomized
    duration, then presses back to return to the rewards page.
    Returns True on success, False if the input field is not found.
    """
    log(f"  Typing search query: '{query}'...")
    search_input = d(resourceId=SEARCH_INPUT_ID)
    if not search_input.exists:
        log("  [FAIL] Search input field not found.")
        return False

    search_input.click()
    search_input.clear_text()   # Fix 4: clear any stale text from a previous search
    search_input.set_text(query)
    time.sleep(0.5)

    # Fix 3: verify text was actually entered — retry set_text once if mismatch
    actual = search_input.get_text()
    if actual != query:
        log(f"  [WARN] Text mismatch (got '{actual}') — retrying set_text...")
        search_input.clear_text()
        search_input.set_text(query)
        time.sleep(0.5)
        actual = search_input.get_text()
        if actual != query:
            log(f"  [FAIL] Text still incorrect after retry (got '{actual}') — aborting search.")
            return False

    log("  Submitting search...")
    d.press("enter")

    hold = random.uniform(SEARCH_HOLD_MIN, SEARCH_HOLD_MAX)
    log(f"  Holding results page for {hold:.1f}s...")
    time.sleep(hold)

    log("  Pressing back to return to rewards page...")
    d.press("back")
    time.sleep(2.5)  # settle after back

    # Fix 2: confirm we actually landed back on the rewards page
    if not _on_rewards_page(d):
        log("  [FAIL] Back press did not return to rewards page — unexpected location.")
        return False

    return True


# ── Recovery ───────────────────────────────────────────────────────

def _recover_to_search_earn(d):
    """
    Unified recovery when any step in the search loop fails.
    Checks current location and applies the appropriate branch to get back
    to the 'Search to earn' row, ready for a retry.

    Location check order:
      1. Search overlay still open → close it; if back on rewards page, locate section and retry directly.
      2. On rewards page landmarks → Branch C, exit cleanly.
      3. Inside Bing, wrong room  → Branch B.
      4. Outside Bing entirely    → Branch A (also Branch B fallback).

    Returns True if successfully positioned at 'Search to earn', False otherwise.
    Max one recovery — cannot loop infinitely.
    """
    # Step 1: close overlay if still open
    closed_overlay = False
    if _on_search_overlay(d):
        _close_search_overlay(d)
        closed_overlay = True

    # Step 2: if we just closed the overlay and landed on rewards page —
    # this is a clean recovery position, locate section and retry directly.
    if closed_overlay and _on_rewards_page(d):
        log("  [RECOVER] Overlay closed, back on rewards page — locating 'Search to earn'...")
        found, _, status = _scroll_to_search_earn(d)
        return found

    # Branch C — on rewards page without having closed an overlay →
    # section genuinely unavailable, exit cleanly.
    if _on_rewards_page(d):
        log("  [RECOVER] On rewards page — 'Search to earn' completed or genuinely unavailable.")
        return False

    package = d.app_current().get("package", "")

    # Branch B — inside Bing but wrong room
    if BING_PACKAGE in package:
        log("  [RECOVER] Wrong room inside Bing — navigating back to home screen...")
        go_back_to_home(d)
        if ensure_home_screen(d) and _navigate_to_rewards(d):
            log("  [RECOVER] Back on Rewards page — scrolling to 'Search to earn'...")
            found, _, status = _scroll_to_search_earn(d)
            if found:
                return True
            log("  [RECOVER] Could not find 'Search to earn' after Branch B — falling through to relaunch...")
        else:
            log("  [RECOVER] Could not reach Rewards page via Branch B — attempting full relaunch...")

    # Branch A — outside Bing entirely, or Branch B fallback
    else:
        log(f"  [RECOVER] Outside Bing (current: {package or 'unknown'}) — relaunching...")

    if launch_bing(d) and ensure_home_screen(d):
        dismiss_popup(d)
        if _navigate_to_rewards(d):
            log("  [RECOVER] Back on Rewards page — scrolling to 'Search to earn'...")
            found, _, status = _scroll_to_search_earn(d)
            if found:
                return True
            log("  [RECOVER] Could not find 'Search to earn' after Branch A — giving up.")
        else:
            log("  [RECOVER] Rewards page unavailable after relaunch — giving up.")
    else:
        log("  [RECOVER] Relaunch failed — giving up.")

    return False


# ── Task entry point ───────────────────────────────────────────────

def run(d):
    """
    Execute the Search to Earn task on an already-connected device.
    Assumes Bing is running and the home screen is confirmed before calling.

    Search count is derived dynamically from the rewards page:
      y_value = daily point limit parsed from 'Search to earn' content-desc
      search_count = (y_value // 3) + random bonus of 1–3

    Returns a result dict with keys: search_count, target_count.
    Returns {"search_count": 0, "target_count": 0} if already completed today.
    Returns None only on hard abort (rewards page unreachable).
    """
    log(f"\nStarting Search to Earn...")

    # Step 0: Clear any popup that may have appeared since startup
    log("\n[0/4] Checking for popups before opening Rewards...")
    dismiss_popup(d)

    # Step 1: Open rewards page
    log("\n[1/4] Opening Rewards page...")
    if not open_rewards_page(d):
        log("[ABORT] Could not open Rewards page.")
        return None

    # Step 2: Wait for rewards page to load
    log("\n[2/4] Waiting for Rewards page to load...")
    if not wait_for_rewards_page(d):
        # Tier 2 popup dismissal may have cold-relaunched back to home screen.
        # Attempt one re-navigation before giving up.
        log("  [RECOVER] Rewards page did not load — attempting re-navigation...")
        if ensure_home_screen(d) and _navigate_to_rewards(d):
            log("  [RECOVER] Re-navigated to Rewards page successfully ✓")
        else:
            log("[ABORT] Rewards page did not load and re-navigation failed.")
            return None

    # Step 3: Scroll to "Search to earn" and parse daily limit
    log("\n[3/4] Locating 'Search to earn' section and parsing daily limit...")
    found, y_value, status = _scroll_to_search_earn(d)

    if not found:
        if status == "done":
            # Already completed today or parse failed — logged inside _scroll_to_search_earn
            go_back_to_home(d)
            return {"search_count": 0, "target_count": 0}

        # status == "exhausted" — scroll attempts ran out, try 3-branch recovery once
        log("  [RECOVER] Scroll exhausted — running location check and recovery...")
        if not _recover_to_search_earn(d):
            log("[ABORT] Could not locate 'Search to earn' after recovery.")
            go_back_to_home(d)
            return {"search_count": 0, "target_count": 0}

        # Retry scroll after successful recovery
        found, y_value, status = _scroll_to_search_earn(d)
        if not found:
            log("[ABORT] Still could not locate 'Search to earn' after recovery.")
            go_back_to_home(d)
            return {"search_count": 0, "target_count": 0}

    # Calculate target: base count from points limit + random bonus
    target_count = (y_value // 3) + random.randint(SEARCH_BONUS_MIN, SEARCH_BONUS_MAX)
    log(f"  Target searches: {y_value} pts ÷ 3 = {y_value // 3} base + bonus = {target_count} total")

    # Generate unique search queries for this run
    log(f"  Fetching {target_count} search queries...")
    queries = get_queries(target_count)

    # Step 4: Search loop
    log(f"\n[4/4] Starting search loop ({target_count} searches)...")
    search_count  = 0
    recovered     = False  # allow max one recovery per run

    for i in range(1, target_count + 1):
        log(f"\n  — Search {i}/{target_count} —")

        # ── Attempt the full search iteration ─────────────────────
        success = (
            _tap_search_to_earn(d)
            and _wait_for_search_overlay(d)
            and _do_single_search(d, queries[i - 1])
        )

        if success:
            search_count += 1
            # Wait between searches (skip after the last one)
            if i < target_count:
                wait = random.uniform(SEARCH_WAIT_MIN, SEARCH_WAIT_MAX)
                log(f"  Waiting {wait:.1f}s before next search...")
                time.sleep(wait)
            continue

        # ── Iteration failed — attempt recovery (once only) ────────
        if recovered:
            log(f"  [STOP] Iteration {i} failed after already recovering once — stopping.")
            break

        log(f"  [!] Iteration {i} failed — attempting recovery...")
        recovered = True

        if not _recover_to_search_earn(d):
            log("  [STOP] Recovery unsuccessful — stopping search loop.")
            break

        # Retry the same iteration index after successful recovery
        log(f"  [RECOVER] Retrying search {i}/{target_count}...")
        success = (
            _tap_search_to_earn(d)
            and _wait_for_search_overlay(d)
            and _do_single_search(d, queries[i - 1])
        )

        if success:
            search_count += 1
            if i < target_count:
                wait = random.uniform(SEARCH_WAIT_MIN, SEARCH_WAIT_MAX)
                log(f"  Waiting {wait:.1f}s before next search...")
                time.sleep(wait)
        else:
            log(f"  [STOP] Retry of iteration {i} also failed — stopping.")
            break

    # Return to Bing home screen
    log("\nReturning to home screen...")
    go_back_to_home(d)

    return {
        "search_count": search_count,
        "target_count": target_count,
    }


def print_report(result):
    """Print the Search to Earn summary report."""
    if result is None:
        print("\n  [!] Search to Earn task did not complete.")
        return

    search_count = result["search_count"]
    target_count = result["target_count"]

    print()
    print("=" * 52)

    if target_count == 0:
        print("  Search to Earn : Already completed today ✓")
        print("=" * 52)
        return

    status = "SUCCESS ✓" if search_count == target_count else "PARTIAL / INCOMPLETE"
    print(f"  Searches Done : {search_count} / {target_count}")
    print(f"  Status        : {status}")
    print("=" * 52)