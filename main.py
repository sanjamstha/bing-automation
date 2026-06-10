"""
main.py — Bing Automation: Entry Point

Automatically detects all connected ADB devices and runs the full automation (Daily Rewards -> Read Articles) on each device in parallel. 
No user input required — just run the script.

Concurrency is controlled by MAX_WORKERS in config.py. If you have 4 devices and MAX_WORKERS=2, the first 2 start immediately and the remaining 2 are queued — each starts as a slot frees up.
"""

from concurrent.futures import ThreadPoolExecutor

from core.device import (
    detect_devices, connect,
    launch_bing, ensure_home_screen,
    dismiss_popup, close_all_tabs,
    log, set_device_label,
)
from config import MAX_WORKERS
from tasks import daily, articles


# ── Startup / teardown ─────────────────────────────────────────────

def _startup(d):
    """
    Shared startup sequence: launch Bing and confirm the home screen.
    Returns True on success, False if either step fails.
    """
    log("[STARTUP] Launching Bing...")
    if not launch_bing(d):
        log("[ABORT] Bing failed to reach foreground.")
        return False

    log("[STARTUP] Confirming home screen...")
    if not ensure_home_screen(d):
        log("[ABORT] Could not confirm home screen.")
        return False

    log("[STARTUP] Checking for popups...")
    dismiss_popup(d)

    return True

def _teardown(d):
    """
    Post-run cleanup: closes all browser tabs accumulated during the run.
    Non-fatal — a failure here does not affect already-printed task results.
    """
    log("[TEARDOWN] Running post-task cleanup...")
    close_all_tabs(d)

# ── Task runners ───────────────────────────────────────────────────

def _run_daily(d):
    log("\n" + "─" * 52)
    log("TASK 1/2 — Daily Rewards")
    log("─" * 52)
    result = daily.run(d)
    daily.print_report(result)


def _run_articles(d):
    log("\n" + "─" * 52)
    log("TASK 2/2 — Read Articles")
    log("─" * 52)
    result = articles.run(d)
    articles.print_report(result)


# ── Per-device entry point (runs inside each thread) ───────────────

def _run_on_device(args):
    """
    Full automation run for a single device.
    Accepts a tuple of (serial, index, total, name) — required because ThreadPoolExecutor.map() passes a single argument per call.
    Label uses the friendly name when provided by the launcher, otherwise falls back to "EMU-N/total".
    """
    serial, index, total, name = args
    label = f"{name}" if name else f"EMU-{index}/{total}"
    set_device_label(label)

    try:
        d = connect(serial)

        if not _startup(d):
            log("Startup failed — skipping this device.")
            return

        _run_daily(d)
        _run_articles(d)
        _teardown(d)

        log("Device run complete ✓")

    except Exception as e:
        log(f"[ERROR] Unhandled exception — device skipped. Reason: {e}")


# ── Main ───────────────────────────────────────────────────────────

def main(device_names=None):
    """
    device_names: optional dict mapping serial -> friendly name, provided by a launcher script. When None (direct run), labels fall back to EMU-N/total format.
    """
    if device_names is None:
        device_names = {}
    print()
    print("=" * 52)
    print("        BING AUTOMATION — STARTING UP             ")
    print("=" * 52)

    # Detect all connected devices (auto-restarts ADB server if needed)
    serials = detect_devices()

    if not serials:
        print("[ERROR] No ADB devices found after ADB server restart.")
        print("        Make sure your emulators are running and visible to ADB.")
        print("        Run `adb devices` to verify.")
        return
    
    if device_names:
        serials = [s for s in serials if s in device_names]
        if not serials:
            print("[ERROR] None of the launcher's devices appeared in adb devices.")
            return
        
    total = len(serials)
    print(f"  Devices found : {total}")
    for i, s in enumerate(serials, start=1):
        name = device_names.get(s, "")
        label = f"{name}" if name else s
        print(f"    {i}. {label} ({s})")
    print(f"  Max parallel  : {MAX_WORKERS}")
    print("=" * 52)
    print()

    # Build argument tuples — executor.map passes one arg per call
    device_args = [
        (serial, index, total, device_names.get(serial, ""))
        for index, serial in enumerate(serials, start=1)
    ]

    # ThreadPoolExecutor queues devices automatically when MAX_WORKERS
    # is less than the total device count — no manual batching needed.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        executor.map(_run_on_device, device_args)

    print()
    print("=" * 52)
    print("  All devices finished.")
    print("=" * 52)


if __name__ == "__main__":
    main()