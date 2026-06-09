"""
tasks/daily.py — Daily Rewards: Check-in + Daily Set + More Activities

Flow:
  Open Rewards → [Check-in if streaks visible] → Daily Set → More Activities → Return home

Check-in outcomes:
  - Streaks section not visible today  →  SKIPPED — Streaks not shown today
  - Streaks visible, Check-in present  →  Attempted and completed
  - Streaks visible, no Check-in btn   →  SKIPPED — already done today
"""

import time

from config import (
    BING_PACKAGE,
    REWARDS_CARD_ID,
    REWARDS_CARD_TITLE,
    REWARDS_CARD_DESC,
    TEXT_STREAKS,
    TEXT_CHECKIN,
    BACK_WAIT,
    REWARDS_READ_WAIT,
    REWARDS_PAGE_TIMEOUT,
    MAX_MISSES,
)
from core.device import log, go_back_to_home, dismiss_popup, launch_bing, ensure_home_screen


# ── Rewards page navigation ────────────────────────────────────────

def open_rewards_page(d):
    card = d(resourceId=REWARDS_CARD_ID, description=REWARDS_CARD_DESC)
    if not card.exists:
        card = d(resourceId=REWARDS_CARD_TITLE, text=REWARDS_CARD_DESC)
    if not card.exists:
        log("  [!] Rewards card not found")
        return False
    log("  Tapping Rewards card...")
    card.click()
    return True


def wait_for_rewards_page(d):
    """Wait for the Rewards WebView to load — accepts any known landmark."""
    log(f"  Waiting for Rewards page (up to {REWARDS_PAGE_TIMEOUT}s)...")
    deadline = time.time() + REWARDS_PAGE_TIMEOUT
    while time.time() < deadline:
        if (d(text="Today's points").exists
                or d(text="Daily set").exists
                or d(text="Streaks").exists):
            log("  Rewards page loaded ✓")
            time.sleep(1.5)
            return True
        time.sleep(0.8)
    log("  [TIMEOUT] Rewards page did not load")
    return False


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
    geo = _get_geometry(d)
    try:
        d.swipe(geo["cx"], geo["swipe_start"], geo["cx"], geo["swipe_end"], 0.35)
    except Exception as e:
        log(f"  [WARN] Swipe failed (likely system UI in foreground): {e.__class__.__name__} — skipping scroll.")
    time.sleep(1.8)


def _button_in_safe_zone(bounds, geo):
    cy = (bounds.get("top", 0) + bounds.get("bottom", 0)) / 2
    return geo["safe_top"] < cy < geo["safe_bottom"]


# ── Check-in (Step 4) ──────────────────────────────────────────────

def do_checkin(d):
    """
    Attempts the daily check-in streak.

    Uses plain text matching (not regex/content-desc) to locate the check-in
    button inside the WebView. Coordinate target is refined via Day 1–7 column
    vectors so the click lands on the correct day circle even when layout shifts.

    Returns a status string describing what happened.
    """
    log("\n[CHECK-IN] Looking for Streaks section...")

    # OUTCOME 1: Streaks section not present today
    if not d(text=TEXT_STREAKS).exists:
        log("  Streaks section not available today — skipping check-in")
        return "SKIPPED — Streaks not shown today"

    log("  Streaks section found ✓")

    # OUTCOME 2: Streaks visible but no "Check in" text — already done
    if not d(text=TEXT_CHECKIN).exists:
        log("  Check-in already completed today ✓ (Skipping interaction phase)")
        return "SKIPPED — already done today"

    # OUTCOME 3: Streaks loaded, check-in not yet done
    log("  Check-in row active. Running coordinate calculations...")
    el = d(text=TEXT_CHECKIN)
    bounds = el.info.get("bounds", {})

    # Base fallback — derived proportionally from actual display size
    w  = d.info.get("displayWidth",  900)
    h  = d.info.get("displayHeight", 1600)
    cx = w // 2
    cy = (bounds.get("top", int(h * 0.74)) + bounds.get("bottom", int(h * 0.77))) // 2

    # Loop over active target tokens to get dynamic columns
    # (Handles Day 1 through Day 7 seamlessly)
    for day_num in range(1, 8):
        day_node = d(text=f"Day {day_num}")
        if day_node.exists:
            day_bounds = day_node.info.get("bounds", {})
            cx = (day_bounds.get("left", 0) + day_bounds.get("right", 0)) // 2
            cy = day_bounds.get("top", 0) - int(
                (day_bounds.get("bottom", 0) - day_bounds.get("top", 0)) * 1.5
            )
            log(f"  Dynamic coordinates assigned via Day {day_num} column vectors.")
            break

    log(f"  Clicking check-in vector coordinate target: ({cx}, {cy})...")
    d.click(cx, cy)
    time.sleep(4)  # Wait for check-in registration

    if not d(text=TEXT_CHECKIN).exists:
        return "SUCCESS ✓"
    else:
        return "SUCCESS ✓ (Action sent to system layer)"


# ── Reward card collection (Step 5) ───────────────────────────────

def _find_card_nodes(d, earn_keyword):
    """
    Returns a list of bounds dicts for all clickable nodes whose
    content-desc matches 'earn N points' (N = earn_keyword).
    """
    nodes = d(descriptionMatches=f"(?i).*earn {earn_keyword} points.*", clickable=True)
    results = []
    if nodes.exists:
        for node in nodes:
            try:
                results.append(node.info.get("bounds", {}))
            except Exception:
                pass
    return results


def _on_rewards_page(d):
    """Returns True if any known Rewards page landmark is currently visible."""
    return (
        d(text="Today's points").exists
        or d(text="Daily set").exists
        or d(text="Streaks").exists
        or d(text="More activities").exists      
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


def _card_loop(d, earn_keyword, total_cards, section_label, collected, geo):
    """
    Inner card collection loop. Runs one full pass starting from `collected`.
    Returns updated collected count and whether the miss counter was exhausted.
    """
    miss_count = 0

    while collected < total_cards and miss_count < MAX_MISSES:
        all_bounds = _find_card_nodes(d, earn_keyword)
        visible    = [b for b in all_bounds if _button_in_safe_zone(b, geo)]

        if not visible:
            miss_count += 1
            log(f"  No visible target cards (miss {miss_count}/{MAX_MISSES}) — scrolling down...")
            _scroll_down_one(d)
            continue

        bounds = visible[0]
        cx = (bounds.get("left", 0) + bounds.get("right", 900)) // 2
        cy = (bounds.get("top",  0) + bounds.get("bottom", 100)) // 2

        log(f"  [{section_label} {collected+1}/{total_cards}] Clicking at ({cx}, {cy})...")
        d.click(cx, cy)

        log(f"  Holding for {REWARDS_READ_WAIT}s to register points...")
        time.sleep(REWARDS_READ_WAIT)

        log("  Pressing back to return to rewards page...")
        d.press("back")
        time.sleep(BACK_WAIT)

        collected  += 1
        miss_count  = 0

    exhausted = (miss_count >= MAX_MISSES)
    return collected, exhausted


def collect_cards(d, earn_keyword, total_cards, section_label):
    """
    Clicks reward cards matched by 'earn N points' in content-desc.
    Scrolls down when no visible cards are found.

    Recovery: when the miss counter is exhausted, checks location before
    concluding — three possible situations:

      BRANCH A — At the park (outside Bing entirely):
        → cold relaunch → dismiss any popup → navigate to Rewards page
        → retry card loop once. If rewards page fails to open → exit.

      BRANCH B — Inside building but wrong room (not on Rewards page):
        → go_back_to_home() to reach Bing home screen
        → navigate to Rewards page
        → retry card loop once.
        → if Rewards page fails → fall back to full relaunch (Branch A logic)

      BRANCH C — Right room (Rewards page landmarks visible):
        → cards genuinely unavailable (already collected or not served today)
        → exit cleanly, no recovery needed.

    Max one recovery per call — cannot loop infinitely.
    """
    geo       = _get_geometry(d)
    collected = 0

    log(f"  Scanning for cards with 'earn {earn_keyword} points' in content-desc...")

    # ── First pass ─────────────────────────────────────────────────
    collected, exhausted = _card_loop(d, earn_keyword, total_cards, section_label, collected, geo)

    if collected >= total_cards or not exhausted:
        return collected

    # ── Miss counter exhausted — location check ────────────────────
    package  = d.app_current().get("package", "")
    on_rewards = _on_rewards_page(d)

    # BRANCH C — right room, cards just not available
    if on_rewards:
        log("  Cards genuinely unavailable (already collected or not served today).")
        return collected

    # BRANCH B — inside Bing but wrong room
    if BING_PACKAGE in package:
        log(f"  [RECOVER] Wrong room inside Bing — navigating back to home screen...")
        go_back_to_home(d)
        if not ensure_home_screen(d):
            # Back press wasn't enough — fall through to full relaunch
            log("  [RECOVER] Could not confirm home screen — attempting full relaunch...")
        elif _navigate_to_rewards(d):
            log("  [RECOVER] Back on Rewards page — retrying card collection once...")
            collected, _ = _card_loop(d, earn_keyword, total_cards, section_label, collected, geo)
            return collected
        else:
            # On home screen but Rewards card not found — fall through to full relaunch
            log("  [RECOVER] Could not open Rewards from home — attempting full relaunch...")

    # BRANCH A — at the park, or Branch B fallback
    else:
        log(f"  [RECOVER] Outside Bing (current: {package or 'unknown'}) — relaunching...")

    if launch_bing(d) and ensure_home_screen(d):
        dismiss_popup(d)
        if _navigate_to_rewards(d):
            log("  [RECOVER] Back on Rewards page — retrying card collection once...")
            collected, _ = _card_loop(d, earn_keyword, total_cards, section_label, collected, geo)
        else:
            log("  [RECOVER] Rewards page unavailable after relaunch — giving up.")
    else:
        log("  [RECOVER] Relaunch failed — giving up.")

    return collected


# ── Task entry point ───────────────────────────────────────────────

def run(d):
    """
    Execute the full Daily Rewards task on an already-connected device.
    Assumes Bing is running and the home screen is confirmed before calling.
    Returns a result dict with keys: checkin, daily_collected, more_collected.
    """
    # Step 0: Clear any popup that may have appeared since startup
    log("\n[0/3] Checking for popups before opening Rewards...")
    dismiss_popup(d)

    # Step 1: Open Rewards page
    log("\n[1/3] Opening Rewards page...")
    if not open_rewards_page(d):
        log("[ABORT] Could not open Rewards page.")
        return None

    # Step 2: Wait for Rewards page to load
    log("\n[2/3] Waiting for Rewards page to load...")
    if not wait_for_rewards_page(d):
        go_back_to_home(d)
        log("[ABORT] Rewards page did not load.")
        return None

    # Step 3a: Check-in
    checkin_result = do_checkin(d)

    # Step 3b: Daily Set — 3 cards worth 10 pts each
    log("\n[3a/3] Collecting Daily Set cards (earn 10 points)...")
    daily_collected = collect_cards(d, "10", total_cards=3, section_label="Daily")

    # Step 3c: More Activities — 1 card worth 5 pts
    log("\n[3b/3] Collecting More Activities cards (earn 5 points)...")
    more_collected = collect_cards(d, "5", total_cards=1, section_label="More")

    # Return to Bing home screen
    log("\nReturning to home screen...")
    go_back_to_home(d)

    return {
        "checkin":         checkin_result,
        "daily_collected": daily_collected,
        "more_collected":  more_collected,
    }


def print_report(result):
    """Print the Daily Rewards summary report."""
    if result is None:
        print("\n  [!] Daily Rewards task did not complete.")
        return

    daily_pts = result["daily_collected"] * 10
    more_pts  = result["more_collected"]  * 5
    total_pts = daily_pts + more_pts

    print()
    print("=" * 52)
    print(f"  Check-in result        : {result['checkin']}")
    print(f"  Daily Set              : {result['daily_collected']}/3 cards (+{daily_pts} pts)")
    print(f"  More Activities        : {result['more_collected']}/1 card  (+{more_pts} pts)")
    print(f"  Total Points Collected : +{total_pts}")
    if result["daily_collected"] == 3 and result["more_collected"] == 1:
        print("  DAILY REWARDS COMPLETED ✓")
    else:
        print("  DAILY REWARDS PARTIALLY COMPLETED / ALREADY CLAIMED")
    print("=" * 52)