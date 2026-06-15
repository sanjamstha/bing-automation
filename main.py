"""
main.py — Bing Automation: Entry Point

Automatically detects all connected ADB devices and runs the full automation (Daily Rewards -> Read Articles) on each device in parallel. 
No user input required — just run the script.

Concurrency is controlled by MAX_WORKERS in config.py. If you have 4 devices and MAX_WORKERS=2, the first 2 start immediately and the remaining 2 are queued — each starts as a slot frees up.
"""

from concurrent.futures import ThreadPoolExecutor
import time
from core.device import (
    detect_devices, connect,
    launch_bing, ensure_home_screen,
    dismiss_popup, close_all_tabs,
    log, set_device_label,
)
from config import MAX_WORKERS, CONNECT_RETRIES, CONNECT_RETRY_WAIT
from tasks import daily, articles, search


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
    log("─" * 52)
    log("TASK 1/3 — Daily Rewards")
    log("─" * 52)
    result = daily.run(d)
    daily.print_report(result)
    return result


def _run_articles(d):
    log("─" * 52)
    log("TASK 2/3 — Read Articles")
    log("─" * 52)
    result = articles.run(d)
    articles.print_report(result)
    return result

def _run_search(d):
    log("─" * 52)
    log("TASK 3/3 — Search")
    log("─" * 52)
    result = search.run(d)
    search.print_report(result)
    return result

# ── Summary report helpers ─────────────────────────────────────────

def _format_checkin(checkin_str):
    """Condenses the verbose checkin result string into a short table cell value."""
    if checkin_str is None:
        return "—"
    s = checkin_str.strip()
    if s.startswith("SUCCESS"):
        return "Y"
    if "already done" in s:
        return "N - done"
    if "not shown" in s:
        return "N - missing"
    # Fallback: truncate to 16 chars so the table doesn't blow up
    return s[:16]


def _format_daily(daily_result):
    """Returns total points string from daily result, e.g. '+35'."""
    if daily_result is None:
        return "—"
    pts = daily_result.get("daily_collected", 0) * 10 + daily_result.get("more_collected", 0) * 5
    return f"+{pts}"


def _format_articles(articles_result):
    """Returns 'read/limit' string, e.g. '11/11'."""
    if articles_result is None:
        return "—"
    return f"{articles_result.get('read_count', 0)}/{articles_result.get('articles_limit', 0)}"


def _format_search(search_result):
    """Returns 'done/target' string, e.g. '17/21'. Shows 'done' if target was 0."""
    if search_result is None:
        return "—"
    target = search_result.get("target_count", 0)
    if target == 0:
        return "done"
    return f"{search_result.get('search_count', 0)}/{target}"


def _print_summary(results):
    """
    Prints a fixed-width summary table of all device results after all
    threads have finished, followed by an errors section.

    Column widths are computed dynamically from the widest value in each
    column so the table stays aligned regardless of device name length.
    """
    # ── Build rows ─────────────────────────────────────────────────
    headers = ["Device Name", "Startup", "Check In", "Daily Set", "Articles Read", "Search to Earn"]

    rows = []
    for r in results:
        if r is None:
            # _run_on_device returned None (connect failed before label was set)
            continue
        rows.append([
            r["label"],
            "True" if r["startup"] else "False",
            _format_checkin(r["daily"].get("checkin") if r["daily"] else None),
            _format_daily(r["daily"]),
            _format_articles(r["articles"]),
            _format_search(r["search"]),
        ])

    # ── Compute column widths ──────────────────────────────────────
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    # ── Render table ───────────────────────────────────────────────
    sep   = "  "  # column separator
    total_width = sum(col_widths) + len(sep) * (len(headers) - 1)
    rule  = "─" * total_width

    def _row_str(cells):
        return sep.join(c.ljust(w) for c, w in zip(cells, col_widths))

    print()
    print("=" * total_width)
    print("  SUMMARY REPORT")
    print("=" * total_width)
    print(_row_str(headers))
    print(rule)
    for row in rows:
        print(_row_str(row))
    print("=" * total_width)

    # ── Errors section ─────────────────────────────────────────────
    all_errors = []
    for r in results:
        if r is None:
            continue
        for err in r.get("errors", []):
            all_errors.append(f"  [{r['label']}] {err}")

    print()
    print(f"Errors Encountered - {len(all_errors)}")
    if all_errors:
        for err in all_errors:
            print(f"  - {err}")
    print()


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

    result = {
        "label":    label,
        "startup":  False,
        "daily":    None,
        "articles": None,
        "search":   None,
        "errors":   [],
    }

    # ── Connection (with retries) ──────────────────────────────────
    d = None
    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            d = connect(serial)
            break
        except Exception as e:
            if attempt < CONNECT_RETRIES:
                log(f"[CONNECT] Attempt {attempt} failed ({e}) — retrying in {CONNECT_RETRY_WAIT}s...")
                time.sleep(CONNECT_RETRY_WAIT)
            else:
                msg = f"Connection failed after {CONNECT_RETRIES} attempts: {e}"
                log(f"[CONNECT] All {CONNECT_RETRIES} attempts failed — skipping device.")
                result["errors"].append(msg)
                return result

    try:
        # ── Startup ────────────────────────────────────────────────
        if not _startup(d):
            log("Startup failed — skipping this device.")
            result["errors"].append("Startup failed (Bing did not reach foreground or home screen unconfirmed)")
            return result

        result["startup"] = True

        # ── Tasks ──────────────────────────────────────────────────
        result["daily"]    = _run_daily(d)
        result["articles"] = _run_articles(d)
        result["search"]   = _run_search(d)
        _teardown(d)
        log("Device run complete ✓")

    except Exception as e:
        msg = f"Unhandled exception: {e}"
        log(f"[ERROR] {msg} — device skipped.")
        result["errors"].append(msg)

    return result


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
    # Results are collected for the summary report printed after all threads finish.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(_run_on_device, device_args))

    print()
    print("=" * 52)
    print("  All devices finished.")
    print("=" * 52)

    _print_summary(results)

if __name__ == "__main__":
    main()