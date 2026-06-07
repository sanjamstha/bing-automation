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