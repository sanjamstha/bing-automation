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
    return True


# ── Screen navigation ──────────────────────────────────────────────

def ensure_home_screen(d):
    """
    Verifies the current activity is the Bing home screen.
    Force-relaunches via explicit activity if not already there.
    """
    activity = d.app_current().get("activity", "")
    if HOME_ACTIVITY in activity:
        log("  Home screen confirmed ✓")
        return True

    log("  Wrong screen — force-launching home...")
    d.app_stop(BING_PACKAGE)
    time.sleep(1)
    d.app_start(BING_PACKAGE, activity=HOME_ACTIVITY)

    deadline = time.time() + 20
    while time.time() < deadline:
        if HOME_ACTIVITY in d.app_current().get("activity", ""):
            log("  Home screen ready ✓")
            time.sleep(2)
            return True
        time.sleep(0.8)

    log("  [FAIL] Could not reach home screen")
    return False


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
