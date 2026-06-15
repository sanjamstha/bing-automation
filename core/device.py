# core/device.py — Shared device helpers (connect, launch, navigate, log)

import subprocess
import threading
import uiautomator2 as u2
import time
from datetime import datetime

from config import (
    BING_PACKAGE,
    HOME_ACTIVITY,
    BACK_BTN_ID,
    BACK_WAIT,
    LAUNCH_SETTLE_WAIT,
    HOME_SETTLE_WAIT,
    POPUP_CONTAINER_ID,
    POPUP_CLOSE_IDS,
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
#
# Each thread stores its own device label via _local.label so that interleaved output from multiple devices is always identifiable.
# Example output with 3 devices running simultaneously:
#   [10:42:01] [EMU-1] Launching Bing...
#   [10:42:01] [EMU-3] Launching Bing...
#   [10:42:04] [EMU-2] Bing foreground confirmed ✓
#   [10:42:05] [EMU-1] Bing foreground confirmed ✓

_local = threading.local()


def set_device_label(label):
    """
    Attach a display label to the current thread.
    Call once per thread immediately after it starts, before any log() calls.
    e.g. set_device_label("EMU-1")
    """
    _local.label = label


def log(msg):
    label  = getattr(_local, "label", None)
    prefix = f"[{label}] " if label else ""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {prefix}{msg}", flush=True)

# ── Device detection ───────────────────────────────────────────────

def _parse_serials(output):
    """Parse adb devices output, return only 'device' status serials."""
    serials = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _adb_devices():
    """Run `adb devices` once and return parsed serials. Empty list on failure."""
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True, text=True, timeout=10,
        )
        return _parse_serials(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def detect_devices():
    """
    Returns a list of all connected device serials in 'device' state.

    Three-stage flow:
    1. Run `adb devices` — if devices found, return immediately.
    2. If empty — wait 5s and retry once (gentle recovery, handles momentary ADB hiccups without killing the MuMu bridge).
    3. If still empty — kill-server -> start-server -> wait 8s -> retry. This is the aggressive last resort for a fully dropped ADB server.
    4. If still empty after all that — return [] and let main() quit.
    """
    # ── Stage 1: First attempt ─────────────────────────────────────
    serials = _adb_devices()
    if serials:
        return serials

    # ── Stage 2: Gentle retry — wait and try again before restarting
    print("[ADB] No devices found — waiting 7s and retrying...")
    time.sleep(7)
    serials = _adb_devices()
    if serials:
        print(f"[ADB] Devices found on retry ✓ — {len(serials)} device(s).")
        return serials

    # ── Stage 3: Aggressive restart — only if gentle retry also failed
    print("[ADB] Still no devices — restarting ADB server (last resort)...")
    try:
        subprocess.run(["adb", "kill-server"], timeout=10, capture_output=True)
        print("[ADB] Server stopped.")
        subprocess.run(["adb", "start-server"], timeout=15, capture_output=True)
        print("[ADB] Server started — waiting 15s for devices to register...")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"[ADB] Server restart failed: {e}")
        return []

    time.sleep(15)  # ← change this if devices still don't appear after restart

    # ── Stage 4: Final attempt ─────────────────────────────────────
    serials = _adb_devices()
    if serials:
        print(f"[ADB] Reconnected successfully — {len(serials)} device(s) found.")
    else:
        print("[ADB] Still no devices after restart.")
    return serials


# ── Device connection ──────────────────────────────────────────────

def connect(serial):
    """
    Connect to a device by serial and return the uiautomator2 handle.
    Accepts emulator serials (emulator-5558), IP:port (127.0.0.1:7555), or USB serials (R3CN90ABCDE) -- uiautomator2 handles all three.
    """
    log(f"Connecting to {serial}...")
    d = u2.connect(serial)
    log(f"  Device: {d.info.get('productName')} "
        f"({d.info.get('displayWidth')}x{d.info.get('displayHeight')})")
    return d


# ── App lifecycle ──────────────────────────────────────────────────

def launch_bing(d):
    """
    Cold-starts Bing from the mobile home screen reliably.
    Uses app_wait (not activity polling) to confirm foreground.
    No activity= param on app_start to avoid silent failures from a hardcoded activity name.
    """
    # Check Bing is installed before attempting launch
    installed = d.shell(f"pm list packages {BING_PACKAGE}").output.strip()
    if BING_PACKAGE not in installed:
        log(f"  [SKIP] Bing not installed on this device — skipping.")
        return False

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

    Fast path  -- already on HOME_ACTIVITY: settle and return True.
    Recovery   -- anywhere else (wrong room OR outside Bing entirely / at the Android launcher): delegate to launch_bing() which does a full app_stop -> app_start cold cycle. Cold-starting always lands on HOME_ACTIVITY regardless of where we were (wrong room, park, etc).
    Explicit activity= param is intentionally avoided -- it is silently ignored by Samsung's activity manager when the app is already in the background.
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
      Pass 1 -- Cold relaunch: if a popup is detected, stop and cold-start Bing (same as the startup sequence). This clears most transient dialogs without needing to know their specific structure.
      Pass 2 -- Targeted tap: if the popup survived the relaunch, fall back to clicking the known close button by resource-id. Extend this list as new popup types are encountered.

    Detection uses android:id/parentPanel -- the standard Android AlertDialog
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
    close_targets = POPUP_CLOSE_IDS
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
    Returns to the Bing home screen using the in-app back button if present, otherwise falls back to the system back key.
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
      Step 1 -- Tap the "Tabs" navbar button  ->  tab switcher opens
      Step 2 -- Tap the 3-dot "More" button   ->  bottom-sheet menu appears
      Step 3 -- Tap "Close all tabs" row      ->  all tabs cleared
      Step 4 -- Tap the "Home" navbar button  ->  return to home feed

    Does NOT touch account/session data -- tabs are completely separate
    from the Microsoft account session stored in Bing's app data.

    Non-fatal: returns True on success, False if any step fails.
    The caller (main._teardown) logs a warning and continues either way.
    """
    log("[TAB CLEANUP] Closing all open tabs...")

    # ── Step 1: Open the tab switcher ─────────────────────────────
    log("  Step 1/4 — Tapping Tabs navbar button...")
    tabs_btn = d(description=NAV_TABS_DESC, clickable=True)
    if not tabs_btn.exists:
        log("  [WARN] Tabs navbar button not found — skipping tab cleanup.")
        return False
    tabs_btn.click()

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
    log("  Step 2/4 — Tapping More (⋯) button...")
    more_btn = d(resourceId=TABS_MORE_BTN_ID)
    if not more_btn.exists:
        log("  [WARN] More button not found — pressing back and skipping.")
        d.press("back")
        return False
    more_btn.click()

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
    log("  Step 4/4 — Returning to Home via navbar...")
    home_btn = d(description=NAV_HOME_DESC, clickable=True)
    if home_btn.exists:
        home_btn.click()
    else:
        d.press("back")
    time.sleep(TAB_NAV_WAIT)

    log("[TAB CLEANUP] Complete ✓")
    return True