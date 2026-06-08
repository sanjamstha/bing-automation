# core/device.py — Shared device helpers (connect, launch, navigate, log)

import uiautomator2 as u2
import time
from datetime import datetime

from config import (
    ADB_ADDRESS,
    BING_PACKAGE,
    HOME_ACTIVITY,
    BACK_BTN_ID,
    BACK_WAIT,
    LAUNCH_SETTLE_WAIT,
    HOME_SETTLE_WAIT,
    POPUP_CONTAINER_ID,
    POPUP_CLOSE_ID,
    NAV_TABS_DESC,
    NAV_HOME_DESC,
    TABS_TITLE_ID,
    TABS_MORE_BTN_ID,
    TABS_ACTION_LIST_ID,
    TABS_CLOSE_ALL_DESC,
    TAB_NAV_WAIT,
    TAB_SWITCHER_TIMEOUT,
)


# ── Logging ────────────────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ── Device connection ──────────────────────────────────────────────

def connect():
    """Connect to the ADB device and return the device handle."""
    log("Connecting...")
    d = u2.connect(ADB_ADDRESS)
    log(f"  Device: {d.info.get('productName')} "
        f"({d.info.get('displayWidth')}x{d.info.get('displayHeight')})")
    return d


# ── App lifecycle ──────────────────────────────────────────────────

def launch_bing(d):
    """
    Cold-starts Bing from the mobile home screen reliably.
    Uses app_wait (not activity polling) to confirm foreground.
    No activity= param on app_start to avoid silent failures
    from a hardcoded activity name.
    """
    log("  Stopping any existing Bing instance...")
    d.app_stop(BING_PACKAGE)
    time.sleep(1)

    log("  Launching Bing (cold start, no activity param)...")
    d.app_start(BING_PACKAGE)

    success = d.app_wait(BING_PACKAGE, front=True, timeout=30)
    if not success:
        log("  [FAIL] Bing did not reach foreground within 30s")
        log("         Is Bing installed? Run: adb shell pm list packages | findstr bing")
        return False
    log("  Bing foreground confirmed ✓")
    log(f"  Settling for {LAUNCH_SETTLE_WAIT}s while UI renders...")
    time.sleep(LAUNCH_SETTLE_WAIT)
    return True


# ── Screen navigation ──────────────────────────────────────────────

def ensure_home_screen(d):
    """
    Verifies the current activity is the Bing home screen.

    Fast path  — already on HOME_ACTIVITY: settle and return True.
    Recovery   — anywhere else (wrong room OR outside Bing entirely / at the
                 Android launcher): delegate to launch_bing() which does a full
                 app_stop → app_start cold cycle. Cold-starting always lands on
                 HOME_ACTIVITY regardless of where we were (wrong room, park, etc).
                 Explicit activity= param is intentionally avoided — it is silently
                 ignored by Samsung's activity manager when the app is already in
                 the background.
    """
    activity = d.app_current().get("activity", "")
    if HOME_ACTIVITY in activity:
        log("  Home screen confirmed ✓")
        log(f"  Settling for {HOME_SETTLE_WAIT}s while widgets draw...")
        time.sleep(HOME_SETTLE_WAIT)
        return True

    log(f"  Not on home screen (current: {activity or 'unknown'}) — cold relaunching Bing...")
    if not launch_bing(d):
        log("  [FAIL] Could not relaunch Bing to reach home screen")
        return False

    # Confirm HOME_ACTIVITY is now active after the relaunch settle wait
    activity = d.app_current().get("activity", "")
    if HOME_ACTIVITY in activity:
        log("  Home screen ready after relaunch ✓")
        log(f"  Settling for {HOME_SETTLE_WAIT}s while widgets draw...")
        time.sleep(HOME_SETTLE_WAIT)
        return True

    log(f"  [FAIL] Still not on home screen after relaunch (current: {activity or 'unknown'})")
    return False


def dismiss_popup(d):
    """
    Detects and dismisses any blocking popup on the current screen.

    Strategy (two-pass):
      Pass 1 — Cold relaunch: if a popup is detected, stop and cold-start
               Bing (same as the startup sequence). This clears most transient
               dialogs without needing to know their specific structure.
      Pass 2 — Targeted tap: if the popup survived the relaunch, fall back to
               clicking the known close button by resource-id. Extend this list
               as new popup types are encountered.

    Detection uses android:id/parentPanel — the standard Android AlertDialog
    wrapper present in all system-style dialogs including the Bing feedback popup.
    """
    if not d(resourceId=POPUP_CONTAINER_ID).exists:
        return  # No popup — nothing to do

    log("  [POPUP] Dialog detected — attempting cold relaunch to clear...")
    d.app_stop(BING_PACKAGE)
    time.sleep(1)
    d.app_start(BING_PACKAGE)
    d.app_wait(BING_PACKAGE, front=True, timeout=30)
    time.sleep(LAUNCH_SETTLE_WAIT)

    # Pass 2: check if popup survived the relaunch
    if not d(resourceId=POPUP_CONTAINER_ID).exists:
        log("  [POPUP] Cleared by relaunch ✓")
        return

    log("  [POPUP] Still visible after relaunch — attempting targeted dismiss...")

    # Known close buttons — add new resource-ids here as more popups are found
    close_targets = [
        POPUP_CLOSE_ID,                         # Bing feedback dialog (do_you_like_close)
        "com.microsoft.bing:id/dialog_close",   # Generic Bing dialog close (future-proofing)
    ]
    for res_id in close_targets:
        btn = d(resourceId=res_id)
        if btn.exists:
            btn.click()
            log(f"  [POPUP] Dismissed via {res_id} ✓")
            time.sleep(1)
            return

    log("  [POPUP] Could not dismiss — no known close button found. Continuing anyway.")


def go_back_to_home(d):
    """
    Returns to the Bing home screen using the in-app back button
    if present, otherwise falls back to the system back key.
    """
    back = d(resourceId=BACK_BTN_ID)
    if back.exists:
        back.click()
    else:
        d.press("back")
    time.sleep(BACK_WAIT)

# ── Tab cleanup ────────────────────────────────────────────────────
 
def close_all_tabs(d):
    """
    Closes every open browser tab via Bing's in-app tab switcher.
 
    Both tasks accumulate tabs during a run:
      - articles.py  opens ~11 tabs (one per article read)
      - daily.py     opens ~4  tabs (one per reward card clicked)
 
    This function is called once at teardown after all tasks finish,
    regardless of which tasks ran.
 
    Flow (selectors derived from UI XML dumps of all 3 screens):
      Step 1 — Tap the "Tabs" navbar button  →  tab switcher opens
      Step 2 — Tap the 3-dot "More" button   →  bottom-sheet menu appears
      Step 3 — Tap "Close all tabs" row      →  all tabs cleared
      Step 4 — Tap the "Home" navbar button  →  return to home feed
 
    Does NOT touch account/session data — tabs are completely separate
    from the Microsoft account session stored in Bing's app data.
 
    Non-fatal: returns True on success, False if any step fails.
    The caller (main._teardown) logs a warning and continues either way.
    """
    log("\n[TAB CLEANUP] Closing all open tabs...")
 
    # ── Step 1: Open the tab switcher ─────────────────────────────
    # The navbar is a Compose view with no resource-ids; we match by
    # content-desc="Tabs" + clickable=True to avoid the inert "selected"
    # variant of the same label that appears on the tab switcher header.
    log("  Step 1/4 — Tapping Tabs navbar button...")
    tabs_btn = d(description=NAV_TABS_DESC, clickable=True)
    if not tabs_btn.exists:
        log("  [WARN] Tabs navbar button not found — skipping tab cleanup.")
        return False
    tabs_btn.click()
 
    # Confirm switcher opened by waiting for its title resource-id
    deadline = time.time() + TAB_SWITCHER_TIMEOUT
    while time.time() < deadline:
        if d(resourceId=TABS_TITLE_ID).exists:
            log("  Tab switcher open ✓")
            break
        time.sleep(0.5)
    else:
        log("  [WARN] Tab switcher did not open — skipping tab cleanup.")
        return False
 
    time.sleep(TAB_NAV_WAIT)
 
    # ── Step 2: Tap the 3-dot More button ─────────────────────────
    # resource-id: com.microsoft.bing:id/sa_tabs_more, top-right corner
    log("  Step 2/4 — Tapping More (⋯) button...")
    more_btn = d(resourceId=TABS_MORE_BTN_ID)
    if not more_btn.exists:
        log("  [WARN] More button not found — pressing back and skipping.")
        d.press("back")
        return False
    more_btn.click()
 
    # Confirm bottom-sheet appeared via its action list resource-id
    deadline = time.time() + TAB_SWITCHER_TIMEOUT
    while time.time() < deadline:
        if d(resourceId=TABS_ACTION_LIST_ID).exists:
            log("  Bottom-sheet menu open ✓")
            break
        time.sleep(0.5)
    else:
        log("  [WARN] Bottom-sheet menu did not appear — pressing back and skipping.")
        d.press("back")
        return False
 
    time.sleep(TAB_NAV_WAIT)
 
    # ── Step 3: Tap "Close all tabs" ──────────────────────────────
    # The text node itself is not clickable; we tap its clickable parent
    # row which carries content-desc="Close all tabs, Button"
    log("  Step 3/4 — Tapping 'Close all tabs'...")
    close_btn = d(description=TABS_CLOSE_ALL_DESC)
    if not close_btn.exists:
        log("  [WARN] 'Close all tabs' row not found — pressing back and skipping.")
        d.press("back")
        return False
    close_btn.click()
    time.sleep(TAB_NAV_WAIT)
    log("  All tabs closed ✓")
 
    # ── Step 4: Return to Home via navbar ─────────────────────────
    # After closing all tabs the switcher remains open; tap Home to dismiss.
    # Fallback to system back if the Home button isn't found (e.g. UI shifted).
    log("  Step 4/4 — Returning to Home via navbar...")
    home_btn = d(description=NAV_HOME_DESC, clickable=True)
    if home_btn.exists:
        home_btn.click()
    else:
        d.press("back")
    time.sleep(TAB_NAV_WAIT)
 
    log("[TAB CLEANUP] Complete ✓")
    return True