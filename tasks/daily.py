"""
tasks/daily.py — Daily Rewards: Check-in + Daily Set + More Activities + Earn Parsing

Flow:
  Open Rewards → [Check-in if streaks visible] → Daily Set → More Activities
  → Scroll to top → Parse "Search to earn" → Parse "Read to earn"
  → Stay on Rewards page (search.py picks up from here)

Check-in outcomes:
  - Streaks section not visible today  →  SKIPPED — Streaks not shown today
  - Streaks visible, Check-in present  →  Attempted and completed
  - Streaks visible, no Check-in btn   →  SKIPPED — already done today

Earn parsing return values (search_earn_y, read_earn_remaining):
  - int   → row is active, use this value for target calculation
  - None  → row not found / parse failed → downstream task uses its own fallback
  - DONE  → row confirmed not clickable → downstream task skips entirely
"""

import time, random
from config import (
    BING_PACKAGE,
    REWARDS_CARD_ID,
    REWARDS_CARD_TITLE,
    REWARDS_CARD_DESC,
    TEXT_STREAKS,
    TEXT_CHECKIN,
    BACK_WAIT,
    REWARDS_READ_WAIT_MIN,
    REWARDS_READ_WAIT_MAX,
    REWARDS_PAGE_TIMEOUT,
    MAX_MISSES,
    MAX_SCROLL_ATTEMPTS,
    POPUP_CONTAINER_ID,
    POPUP_CLOSE_IDS,
    HOME_ACTIVITY,
    SEARCH_TO_EARN_DESC,
    READ_TO_EARN_DESC,
)
from core.device import log, go_back_to_home, dismiss_popup, launch_bing, ensure_home_screen
from tasks.points import get_current_points

# ── Sentinel ───────────────────────────────────────────────────────
# Signals that a row was confirmed not-clickable (already done today).
# Distinct from None (parse failed / not found → use fallback).
DONE = object()

# ── Rewards page navigation ────────────────────────────────────────

def open_rewards_page(d):
    def _find_card():
        card = d(resourceId=REWARDS_CARD_ID, description=REWARDS_CARD_DESC)
        if not card.exists:
            card = d(resourceId=REWARDS_CARD_TITLE, text=REWARDS_CARD_DESC)
        if not card.exists:
            return False
        log("  Tapping Rewards card...")
        card.click()
        return True

    # First attempt
    if _find_card():
        return True

    # Card not found — check current location and recover
    package  = d.app_current().get("package", "")
    activity = d.app_current().get("activity", "")

    # Branch C — already on home screen, selectors likely changed
    if BING_PACKAGE in package and HOME_ACTIVITY in activity:
        log("  [!] Rewards card not found on home screen.")
        log("  [!] Already on home screen — selectors may have changed due to a Bing update or device variation.")
        log(f"  [!] Check REWARDS_CARD_ID and REWARDS_CARD_TITLE in config.py.")
        return False

    # Branch B — inside Bing but wrong room
    if BING_PACKAGE in package:
        log("  [RECOVER] Wrong room inside Bing — navigating back to home screen...")
        go_back_to_home(d)
        if ensure_home_screen(d):
            log("  [RECOVER] Back on home screen — retrying Rewards card lookup...")
            if _find_card():
                return True
            log("  [RECOVER] Card still not found after Branch B — falling through to relaunch...")
        else:
            log("  [RECOVER] Could not reach home screen via back — attempting full relaunch...")

    # Branch A — outside Bing entirely, or Branch B fallback
    else:
        log(f"  [RECOVER] Outside Bing (current: {package or 'unknown'}) — relaunching...")

    if launch_bing(d) and ensure_home_screen(d):
        log("  [RECOVER] Back on home screen after relaunch — retrying Rewards card lookup...")
        if _find_card():
            return True
        log("  [!] Card still not found after relaunch — selectors may have changed due to a Bing update or device variation.")
        log(f"  [!] Check REWARDS_CARD_ID and REWARDS_CARD_TITLE in config.py.")
    else:
        log("  [RECOVER] Relaunch failed — giving up.")

    return False

def wait_for_rewards_page(d):
    """
    Wait for the Rewards WebView to load — accepts any known landmark.
    Two-tier popup handling runs on every polling iteration:
      Tier 1 — Known close button found:
        Click it, stay on the Rewards page, and keep polling. This is the ideal path — no navigation away.
      Tier 2 — Popup present but no known close button:
        Delegate to dismiss_popup() which does a cold relaunch back to the Bing home screen. Return False immediately so run() can attempt re-navigation to the Rewards page rather than burning the timeout.
    """

    log(f"  Waiting for Rewards page (up to {REWARDS_PAGE_TIMEOUT}s)...")
    # Known close buttons — mirrors the list in dismiss_popup()
    _close_targets = POPUP_CLOSE_IDS

    deadline = time.time() + REWARDS_PAGE_TIMEOUT
    while time.time() < deadline:
        if (d(text="Today's points").exists
                or d(text="Daily set").exists
                or d(text="Streaks").exists):
            log("  Rewards page loaded ✓")
            time.sleep(1.5)
            return True

        if d(resourceId=POPUP_CONTAINER_ID).exists:
            # Tier 1: try known close buttons — stay on Rewards page
            dismissed = False
            for res_id in _close_targets:
                btn = d(resourceId=res_id)
                if btn.exists:
                    btn.click()
                    log(f"  [POPUP] Dismissed via {res_id} — continuing to wait for Rewards page...")
                    time.sleep(1.0)
                    dismissed = True
                    break

            if dismissed:
                continue  # Resume polling — still on Rewards page

            # Tier 2: unknown popup — cold relaunch via dismiss_popup(), return early
            log("  [POPUP] Unknown popup blocking Rewards page — delegating to dismiss_popup()...")
            dismiss_popup(d)
            log("  [POPUP] Cold relaunch complete — returning False for run() to re-navigate.")
            return False

        time.sleep(0.8)

    log("  [TIMEOUT] Rewards page did not load")
    return False


# ── Geometry helpers ───────────────────────────────────────────────

def _get_geometry(d):
    w = d.info.get("displayWidth",  900)
    h = d.info.get("displayHeight", 1600)
    return {
        "w":           w,
        "h":           h,
        "cx":          w // 2,
        "swipe_start": int(h * 0.70),
        "swipe_end":   int(h * 0.35),
        "safe_top":    int(h * 0.12),
        "safe_bottom": int(h * 0.92),
    }


def _scroll_down_one(d):
    geo   = _get_geometry(d)
    x     = geo["cx"]          + random.randint(-int(geo["w"] * 0.13), int(geo["w"] * 0.13))
    start = geo["swipe_start"] + random.randint(-int(geo["h"] * 0.04), int(geo["h"] * 0.04))
    end   = geo["swipe_end"]   + random.randint(-int(geo["h"] * 0.04), int(geo["h"] * 0.04))
    try:
        d.swipe(x, start, x, end, 0.35)
    except Exception as e:
        log(f"  [WARN] Swipe failed: {e.__class__.__name__} — skipping scroll.")
    time.sleep(1.8)


def _button_in_safe_zone(bounds, geo):
    cy = (bounds.get("top", 0) + bounds.get("bottom", 0)) / 2
    return geo["safe_top"] < cy < geo["safe_bottom"]


def _in_safe_zone(bounds, geo):
    """Returns True if the element's vertical center is within the safe interaction zone."""
    cy = (bounds.get("top", 0) + bounds.get("bottom", 0)) / 2
    return geo["safe_top"] < cy < geo["safe_bottom"]


# ── Check-in ───────────────────────────────────────────────────────

def do_checkin(d):
    """
    Attempts the daily check-in streak.

    Uses plain text matching (not regex/content-desc) to locate the check-in
    button inside the WebView. Coordinate target is refined via Day 1–7 column
    vectors so the click lands on the correct day circle even when layout shifts.

    Returns a status string describing what happened.
    """
    log(" [CHECK-IN] Looking for Streaks section...")

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


# ── Reward card collection ─────────────────────────────────────────

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
            log(f"  No visible target cards (miss {miss_count + 1}/{MAX_MISSES}) — scrolling down...")
            _scroll_down_one(d)
            miss_count += 1
            if miss_count >= MAX_MISSES:
                all_bounds = _find_card_nodes(d, earn_keyword)
                visible    = [b for b in all_bounds if _button_in_safe_zone(b, geo)]
                if visible:
                    log("  Cards appeared after final scroll — continuing...")
                    miss_count = 0
                else:
                    break
            continue

        bounds = visible[0]
        cx = (bounds.get("left", 0) + bounds.get("right", 900)) // 2
        cy = (bounds.get("top",  0) + bounds.get("bottom", 100)) // 2

        log(f"  [{section_label} {collected+1}/{total_cards}] Clicking at ({cx}, {cy})...")
        d.click(cx, cy)

        hold = random.uniform(REWARDS_READ_WAIT_MIN, REWARDS_READ_WAIT_MAX)
        log(f"  Holding for {hold:.1f}s to register points...")
        time.sleep(hold)

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
    package    = d.app_current().get("package", "")
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


# ── Earn row parsing (called after card collection) ────────────────

def _scroll_to_top(d):
    """
    Scrolls the rewards page back to the top using uiautomator2's built-in
    scroll-to-beginning. Falls back to a fixed number of upward swipes if
    no scrollable container is found.
    """
    log("  Scrolling rewards page back to top...")
    try:
        scrollable = d(scrollable=True)
        if scrollable.exists:
            scrollable.scroll.toBeginning(steps=40)
            time.sleep(1.5)
            return
    except Exception as e:
        log(f"  [WARN] scroll.toBeginning failed ({e.__class__.__name__}) — falling back to swipes.")

    # Fallback: swipe down (scroll up) several times
    geo = _get_geometry(d)
    for _ in range(6):
        try:
            # Swipe direction reversed: finger moves DOWN to scroll content UP to top
            d.swipe(geo["cx"], geo["swipe_end"], geo["cx"], geo["swipe_start"], 0.35)
        except Exception:
            pass
        time.sleep(1.0)


def _parse_search_earn(d):
    """
    Scrolls to find the 'Search to earn' row and parses its daily point limit.

    Returns:
      int  — row is active; this is the Y value (daily point limit)
      DONE — row is not clickable (already completed today)
      None — row not found or parse failed (caller uses fallback)
    """
    log("  Parsing 'Search to earn' row...")
    geo = _get_geometry(d)

    for attempt in range(1, MAX_SCROLL_ATTEMPTS + 1):
        row = d(descriptionContains=SEARCH_TO_EARN_DESC)
        if row.exists:
            bounds = row.info.get("bounds", {})
            if _in_safe_zone(bounds, geo):
                info = row.info
                if not info.get("clickable", False):
                    log("  'Search to earn' not clickable — already done today ✓")
                    return DONE
                desc    = info.get("contentDescription", "")
                y_value = _parse_y_from_search_desc(desc)
                if y_value is None:
                    log(f"  [FAIL] Could not parse search limit from: '{desc}'")
                    return None
                log(f"  'Search to earn' parsed: {y_value} pts limit ✓")
                return y_value
            else:
                log("  'Search to earn' found but outside safe zone — scrolling into view...")
        else:
            done_row = d(textContains=SEARCH_TO_EARN_DESC)
            if done_row.exists and not done_row.info.get("clickable", True):
                log("  'Search to earn' completed row found — already done today ✓")
                return DONE
            log(f"  'Search to earn' not visible — scrolling (attempt {attempt}/{MAX_SCROLL_ATTEMPTS})...")

        _scroll_down_one(d)

    # Final last-chance scan
    row = d(descriptionContains=SEARCH_TO_EARN_DESC)
    if row.exists:
        bounds = row.info.get("bounds", {})
        if _in_safe_zone(bounds, geo):
            info = row.info
            if not info.get("clickable", False):
                log("  'Search to earn' not clickable — already done today ✓")
                return DONE
            desc    = info.get("contentDescription", "")
            y_value = _parse_y_from_search_desc(desc)
            if y_value is not None:
                log(f"  'Search to earn' parsed on final scroll: {y_value} pts ✓")
                return y_value

    done_row = d(textContains=SEARCH_TO_EARN_DESC)
    if done_row.exists and not done_row.info.get("clickable", True):
        log("  'Search to earn' completed row found on final scan ✓")
        return DONE

    log("  [FAIL] 'Search to earn' not found after max scroll attempts.")
    return None


def _parse_read_earn(d):
    """
    Scrolls to find the 'Read to earn' row and parses the remaining point balance.

    Returns:
      int  — row is active; this is remaining = Y - X
      DONE — row is not clickable (already completed today)
      None — row not found or parse failed (caller uses fallback)
    """
    log("  Parsing 'Read to earn' row...")
    geo = _get_geometry(d)

    for attempt in range(1, MAX_SCROLL_ATTEMPTS + 1):
        row = d(descriptionContains=READ_TO_EARN_DESC)
        if row.exists:
            bounds = row.info.get("bounds", {})
            if _in_safe_zone(bounds, geo):
                info = row.info
                if not info.get("clickable", False):
                    log("  'Read to earn' not clickable — already done today ✓")
                    return DONE
                desc = info.get("contentDescription", "")
                x_value, y_value = _parse_xy_from_read_desc(desc)
                if x_value is None or y_value is None:
                    log(f"  [FAIL] Could not parse read limit from: '{desc}'")
                    return None
                remaining = y_value - x_value
                log(f"  'Read to earn' parsed: {x_value}/{y_value} pts — {remaining} remaining ✓")
                return remaining
            else:
                log("  'Read to earn' found but outside safe zone — scrolling into view...")
        else:
            done_row = d(textContains=READ_TO_EARN_DESC)
            if done_row.exists and not done_row.info.get("clickable", True):
                log("  'Read to earn' completed row found — already done today ✓")
                return DONE
            log(f"  'Read to earn' not visible — scrolling (attempt {attempt}/{MAX_SCROLL_ATTEMPTS})...")

        _scroll_down_one(d)

    # Final last-chance scan
    row = d(descriptionContains=READ_TO_EARN_DESC)
    if row.exists:
        bounds = row.info.get("bounds", {})
        if _in_safe_zone(bounds, geo):
            info = row.info
            if not info.get("clickable", False):
                log("  'Read to earn' not clickable — already done today ✓")
                return DONE
            desc = info.get("contentDescription", "")
            x_value, y_value = _parse_xy_from_read_desc(desc)
            if x_value is not None and y_value is not None:
                remaining = y_value - x_value
                log(f"  'Read to earn' parsed on final scroll: {remaining} remaining ✓")
                return remaining

    done_row = d(textContains=READ_TO_EARN_DESC)
    if done_row.exists and not done_row.info.get("clickable", True):
        log("  'Read to earn' completed row found on final scan ✓")
        return DONE

    log("  [FAIL] 'Read to earn' not found after max scroll attempts.")
    return None


def _parse_y_from_search_desc(desc):
    """
    Parses Y (daily point limit) from 'Search to earn' content-desc.
    Expected format: "Search to earn, , 6 out of 60 points earned"
    Returns int or None.
    """
    try:
        after = desc.split("out of ")[1]   # "60 points earned"
        y_str = after.split(" points")[0]  # "60"
        return int(y_str.strip())
    except (IndexError, ValueError):
        return None


def _parse_xy_from_read_desc(desc):
    """
    Parses X and Y from 'Read to earn' content-desc.
    Expected format: "Read to earn, , 12 out of 30 points earned"
    Returns (x_value, y_value) as ints, or (None, None) on failure.
    """
    try:
        before, after = desc.split("out of ")
        x_str = before.strip().split(" ")[-1]
        y_str = after.split(" points")[0]
        return int(x_str.strip()), int(y_str.strip())
    except (IndexError, ValueError):
        return None, None


# ── Task entry point ───────────────────────────────────────────────

def run(d):
    """
    Execute the full Daily Rewards task on an already-connected device.
    Assumes Bing is running and the home screen is confirmed before calling.

    After collecting cards, scrolls the rewards page back to the top and
    parses Search to earn then Read to earn — so search.py can pick up
    directly from this page without a separate rewards page visit.

    Does NOT return to the home screen — search.py starts from here.

    Returns a result dict with keys:
      checkin, daily_collected, more_collected, current_points,
      search_earn_y, read_earn_remaining

    search_earn_y / read_earn_remaining:
      int  → active row, use this value
      DONE → confirmed done today, downstream task skips
      None → not found / parse failed, downstream task uses its own fallback
    """
    # Step 0: Clear any popup that may have appeared since startup
    log(" [0/4] Checking for popups before opening Rewards...")
    dismiss_popup(d)

    # Step 1: Open Rewards page
    log(" [1/4] Opening Rewards page...")
    if not open_rewards_page(d):
        log("[ABORT] Could not open Rewards page.")
        return None

    # Step 2: Wait for Rewards page to load
    log(" [2/4] Waiting for Rewards page to load...")
    if not wait_for_rewards_page(d):
        # A Tier 2 popup dismissal cold-relaunches Bing back to the home screen.
        # Attempt one re-navigation to the Rewards page before giving up.
        log("  [RECOVER] Rewards page did not load — checking if we can re-navigate...")
        if ensure_home_screen(d) and _navigate_to_rewards(d):
            log("  [RECOVER] Re-navigated to Rewards page — retrying load wait...")
            if not wait_for_rewards_page(d):
                log("[ABORT] Rewards page still did not load after recovery.")
                return None
        else:
            log("[ABORT] Rewards page did not load and re-navigation failed.")
            return None

    # Step 2b: Read current points balance before any actions change it
    log(" [2b/4] Reading current points balance...")
    current_points = get_current_points(d)

    # Step 3a: Check-in
    checkin_result = do_checkin(d)

    # Step 3b: Daily Set — 3 cards worth 10 pts each
    log(" [3a/4] Collecting Daily Set cards (earn 10 points)...")
    daily_collected = collect_cards(d, "10", total_cards=3, section_label="Daily")

    # Step 3c: More Activities — cards worth 5 pts each
    log(" [3b/4] Collecting More Activities cards (earn 5 points)...")
    more_collected = collect_cards(d, "5", total_cards=2, section_label="More")

    # Step 4: Scroll to top, then parse earn rows for search.py and articles.py
    log(" [4/4] Parsing earn rows for downstream tasks...")
    if not _on_rewards_page(d):
        log("  [WARN] Not on rewards page after card collection — attempting recovery...")
        if not _navigate_to_rewards(d):
            log("  [WARN] Could not recover to rewards page — search.py and articles.py will handle independently.")
            go_back_to_home(d)
            search_earn_y       = None
            read_earn_remaining = None
        else:
            _scroll_to_top(d)
            search_earn_y       = _parse_search_earn(d)
            read_earn_remaining = _parse_read_earn(d)
    else:
        _scroll_to_top(d)
        search_earn_y       = _parse_search_earn(d)
        read_earn_remaining = _parse_read_earn(d)

    # Stay on rewards page — search.py picks up from here
    log(" Daily task complete. Staying on Rewards page for search.py ✓")

    return {
        "checkin":            checkin_result,
        "daily_collected":    daily_collected,
        "more_collected":     more_collected,
        "current_points":     current_points,
        "search_earn_y":      search_earn_y,
        "read_earn_remaining": read_earn_remaining,
    }


def print_report(result):
    """Print the Daily Rewards summary report."""
    if result is None:
        print("   [!] Daily Rewards task did not complete.")
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