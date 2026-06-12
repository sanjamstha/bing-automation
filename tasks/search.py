"""
tasks/search.py — Search to Earn

Flow:
  Start on Bing homepage → Open Rewards page → Scroll until "Search to earn" is visible → Tap "Search to earn" → Wait for search overlay → Type query → Hold results → Back → Wait between searches → Repeat for SEARCH_COUNT total searches → Return to home screen

Recovery: when any step in the search loop fails, a unified location check runs a 3-branch strategy before retrying once:

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

from config import BING_PACKAGE
from core.device import (
    log,
    go_back_to_home,
    launch_bing,
    ensure_home_screen,
    dismiss_popup,
)
from tasks.daily import open_rewards_page, wait_for_rewards_page


# ── Local constants (will move to config.py when scaling) ──────────

SEARCH_ITEM         = "venus"
SEARCH_COUNT        = 2

SEARCH_HOLD_MIN     = 4     # seconds to hold on results page (min)
SEARCH_HOLD_MAX     = 6     # seconds to hold on results page (max)
SEARCH_WAIT_MIN     = 8     # seconds to wait between searches (min)
SEARCH_WAIT_MAX     = 12    # seconds to wait between searches (max)

SEARCH_OVERLAY_ID   = "com.microsoft.bing:id/input_hint_view"  # confirms overlay is open
SEARCH_INPUT_ID     = "com.microsoft.bing:id/input"            # EditText to type into
SEARCH_ACTION_BACK  = "com.microsoft.bing:id/action_back"      # close button on overlay
SEARCH_TO_EARN_DESC = "Search to earn"                         # descriptionContains selector

MAX_SCROLL_ATTEMPTS = 8     # max swipes before giving up on finding "Search to earn"
OVERLAY_TIMEOUT     = 10    # seconds to wait for search overlay to open

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

def _scroll_to_search_earn(d):
    """
    Scrolls down the rewards page until the 'Search to earn' row is visible
    AND within the safe interaction zone.

    Final-scroll last-chance: after exhausting MAX_SCROLL_ATTEMPTS, does one
    final scan before returning False — mirrors _card_loop's behaviour in daily.py.

    Returns True if found in safe zone, False if scroll attempts exhausted.
    """
    log("  Scrolling to find 'Search to earn' section...")
    geo = _get_geometry(d)

    for attempt in range(1, MAX_SCROLL_ATTEMPTS + 1):
        row = d(descriptionContains=SEARCH_TO_EARN_DESC)
        if row.exists:
            bounds = row.info.get("bounds", {})
            if _in_safe_zone(bounds, geo):
                log("  'Search to earn' row visible and in safe zone ✓")
                return True
            else:
                log("  Row found but outside safe zone — scrolling into view...")
        else:
            log(f"  Not visible yet — scrolling (attempt {attempt}/{MAX_SCROLL_ATTEMPTS})...")

        _scroll_down_one(d)

    # Final-scroll last-chance check
    row = d(descriptionContains=SEARCH_TO_EARN_DESC)
    if row.exists:
        bounds = row.info.get("bounds", {})
        if _in_safe_zone(bounds, geo):
            log("  'Search to earn' appeared on final scroll ✓")
            return True

    log("  [FAIL] 'Search to earn' not found after max scroll attempts.")
    return False


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
    Unified recovery when any step in the search loop fails. Checks current location and applies the appropriate branch to get back to the 'Search to earn' row, ready for a retry. 

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
    
    # Step 2: if we just closed the overlay and landed on rewards page — this is a clean recovery position, locate section and retry directly.
    if closed_overlay and _on_rewards_page(d):
        log("  [RECOVER] Overlay closed, back on rewards page — locating 'Search to earn'...")
        return _scroll_to_search_earn(d)

    # Branch C — on rewards page without having closed an overlay → section genuinely unavailable, exit cleanly.
    if _on_rewards_page(d):
        log("  [RECOVER] On rewards page — 'Search to earn' genuinely unavailable.")
        return False

    package = d.app_current().get("package", "")

    # Branch B — inside Bing but wrong room
    if BING_PACKAGE in package:
        log("  [RECOVER] Wrong room inside Bing — navigating back to home screen...")
        go_back_to_home(d)
        if ensure_home_screen(d) and _navigate_to_rewards(d):
            log("  [RECOVER] Back on Rewards page — scrolling to 'Search to earn'...")
            if _scroll_to_search_earn(d):
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
            if _scroll_to_search_earn(d):
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
    Returns a result dict with keys: search_count, target_count.
    """
    log(f"\nStarting Search to Earn — Target: {SEARCH_COUNT} searches, query: '{SEARCH_ITEM}'")

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

    # Step 3: Scroll to "Search to earn"
    log("\n[3/4] Locating 'Search to earn' section...")
    if not _scroll_to_search_earn(d):
        log("[ABORT] Could not locate 'Search to earn' section.")
        return None

    # Step 4: Search loop
    log(f"\n[4/4] Starting search loop ({SEARCH_COUNT} searches)...")
    search_count  = 0
    recovered     = False  # allow max one recovery per run

    for i in range(1, SEARCH_COUNT + 1):
        log(f"\n  — Search {i}/{SEARCH_COUNT} —")

        # ── Attempt the full search iteration ─────────────────────
        success = (
            _tap_search_to_earn(d)
            and _wait_for_search_overlay(d)
            and _do_single_search(d, SEARCH_ITEM)
        )

        if success:
            search_count += 1
            # Wait between searches (skip after the last one)
            if i < SEARCH_COUNT:
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
        log(f"  [RECOVER] Retrying search {i}/{SEARCH_COUNT}...")
        success = (
            _tap_search_to_earn(d)
            and _wait_for_search_overlay(d)
            and _do_single_search(d, SEARCH_ITEM)
        )

        if success:
            search_count += 1
            if i < SEARCH_COUNT:
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
        "target_count": SEARCH_COUNT,
    }


def print_report(result):
    """Print the Search to Earn summary report."""
    if result is None:
        print("\n  [!] Search to Earn task did not complete.")
        return

    search_count = result["search_count"]
    target_count = result["target_count"]
    status = "SUCCESS ✓" if search_count == target_count else "PARTIAL / INCOMPLETE"

    print()
    print("=" * 52)
    print(f"  Searches Done : {search_count} / {target_count}")
    print(f"  Status        : {status}")
    print("=" * 52)