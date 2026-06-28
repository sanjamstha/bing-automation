"""
main.py — Bing Automation: Entry Point

Automatically detects all connected ADB devices and runs the full automation
(Daily Rewards → Search → Read Articles) on each device in parallel.
No user input required — just run the script.

Concurrency is controlled by MAX_WORKERS in config.py. If you have 4 devices
and MAX_WORKERS=2, the first 2 start immediately and the remaining 2 are
queued — each starts as a slot frees up.

Rewards page visit reduction:
  Initial pass  — 1 visit (daily opens it, search picks up from there,
                            articles starts from home with pre-parsed value)
  Recheck pass  — 1 visit (same hand-off pattern)
  Total: 2 visits per device run (down from 6).
"""

from concurrent.futures import ThreadPoolExecutor
import time, os
from datetime import datetime
from core.device import (
    detect_devices, connect,
    launch_bing, ensure_home_screen,
    dismiss_popup, close_all_tabs,
    log, set_device_label,
)
from config import MAX_WORKERS, CONNECT_RETRIES, CONNECT_RETRY_WAIT
from tasks import daily, articles, search
from tasks.daily import DONE


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


def _run_search(d, search_earn_y=None):
    log("─" * 52)
    log("TASK 2/3 — Search")
    log("─" * 52)
    result = search.run(d, search_earn_y=search_earn_y)
    search.print_report(result)
    return result


def _run_articles(d, read_earn_remaining=None):
    log("─" * 52)
    log("TASK 3/3 — Read Articles")
    log("─" * 52)
    result = articles.run(d, read_earn_remaining=read_earn_remaining)
    articles.print_report(result)
    return result


# ── Value extraction helpers ───────────────────────────────────────

def _extract_earn_values(daily_result):
    """
    Pulls search_earn_y and read_earn_remaining out of daily's result dict.
    Returns (None, None) if daily_result is None (daily aborted).
    Both values may be: int (active), DONE (confirmed done), or None (not found).
    """
    if daily_result is None:
        return None, None
    return (
        daily_result.get("search_earn_y"),
        daily_result.get("read_earn_remaining"),
    )


# ── Recheck ────────────────────────────────────────────────────────

def _recheck_on_device(d, result):
    """
    Reruns all 3 tasks once after the initial pass, before teardown.

    daily.run() always re-opens the rewards page and re-parses fresh
    search_earn_y and read_earn_remaining values:
      - DONE  → task was already completed; downstream skips it
      - int   → task still has work; downstream runs it (search picks up
                from the same rewards page, articles from home)
      - None  → couldn't parse; each downstream task uses its own fallback

    This means the recheck costs exactly 1 rewards page visit regardless
    of which tasks still have work remaining.
    """
    log("─" * 52)
    log("RECHECK PASS")
    log("─" * 52)

    daily_result = _run_daily(d)
    result["daily"] = daily_result

    search_earn_y, read_earn_remaining = _extract_earn_values(daily_result)

    # Search picks up from the rewards page daily left open
    result["search"] = _run_search(d, search_earn_y=search_earn_y)

    # Articles starts from home (search returned home at end of its run)
    result["articles"] = _run_articles(d, read_earn_remaining=read_earn_remaining)


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
    return s[:16]


def _format_points(daily_result):
    """Returns the comma-formatted current points balance, e.g. '3,753'."""
    if daily_result is None:
        return "—"
    points = daily_result.get("current_points")
    if points is None:
        return "—"
    return f"{points:,}"


def _format_daily(daily_result):
    """Returns total points string from daily result, e.g. '+35'. Shows 'done' if nothing collected."""
    if daily_result is None:
        return "—"
    pts = daily_result.get("daily_collected", 0) * 10 + daily_result.get("more_collected", 0) * 5
    if pts == 0:
        return "done"
    return f"+{pts}"


def _format_articles(articles_result):
    """Returns 'read/limit' string, e.g. '11/11'. Shows 'done' if limit was 0."""
    if articles_result is None:
        return "—"
    limit = articles_result.get("articles_limit", 0)
    if limit == 0:
        return "done"
    return f"{articles_result.get('read_count', 0)}/{limit}"


def _format_search(search_result):
    """Returns 'done/target' string, e.g. '17/21'. Shows 'done' if target was 0."""
    if search_result is None:
        return "—"
    target = search_result.get("target_count", 0)
    if target == 0:
        return "done"
    return f"{search_result.get('search_count', 0)}/{target}"


def _build_summary_lines(results):
    """
    Builds the summary table and errors section as a list of strings.
    Used by both _print_summary() (console) and _save_summary() (file)
    so the output is always identical between the two.
    """
    headers = ["Device Name", "Startup", "Current Pts", "Check In", "Daily Set", "Articles Read", "Search to Earn"]

    rows = []
    for r in results:
        if r is None:
            continue
        rows.append([
            r["label"],
            "True" if r["startup"] else "False",
            _format_points(r["daily"]),
            _format_checkin(r["daily"].get("checkin") if r["daily"] else None),
            _format_daily(r["daily"]),
            _format_articles(r["articles"]),
            _format_search(r["search"]),
        ])

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    sep         = "  "
    total_width = sum(col_widths) + len(sep) * (len(headers) - 1)
    rule        = "-" * total_width

    def _row_str(cells):
        return sep.join(c.ljust(w) for c, w in zip(cells, col_widths))

    lines = []
    lines.append("")
    lines.append("--- SUMMARY REPORT ---")
    lines.append(rule)
    lines.append(_row_str(headers))
    lines.append(rule)
    for row in rows:
        lines.append(_row_str(row))

    all_errors = []
    for r in results:
        if r is None:
            continue
        for err in r.get("errors", []):
            all_errors.append(f"  [{r['label']}] {err}")

    lines.append("")
    lines.append(f"Errors Encountered - {len(all_errors)}")
    if all_errors:
        for err in all_errors:
            lines.append(f"  - {err}")
    lines.append("")

    return lines


def _print_summary(results):
    """Prints the summary table and errors section to the console."""
    for line in _build_summary_lines(results):
        print(line)


def _save_summary(results, run_start):
    """
    Appends the summary report to bing-logs/YYYY-MM-DD.log.
    Each run is prefixed with a Date header so multiple runs on the
    same day are clearly separated in the file.
    Creates the bing-logs directory if it does not exist.
    Non-fatal — a failure here does not affect anything else.
    """
    try:
        os.makedirs("bing-logs", exist_ok=True)
        today    = run_start.strftime("%Y-%m-%d")
        filepath = os.path.join("bing-logs", f"{today}.log")
        lines    = _build_summary_lines(results)

        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"Date - {run_start.strftime('%Y/%m/%d')}\n")
            f.write(f"Start time - {run_start.strftime('%H:%M:%S')}\n")
            f.write(f"Completion time - {datetime.now().strftime('%H:%M:%S')}\n")
            for line in lines:
                f.write(line + "\n")
            f.write("\n")

        print(f"  Summary saved → bing-logs/{today}.log")

    except Exception as e:
        print(f"  [WARN] Could not save summary to file: {e}")


# ── Per-device entry point (runs inside each thread) ───────────────

def _run_on_device(args):
    """
    Full automation run for a single device.
    Accepts a tuple of (serial, index, total, name) — required because
    ThreadPoolExecutor.map() passes a single argument per call.

    Task order: daily → search → articles
      - daily opens the rewards page, parses earn values, stays on it
      - search picks up from that rewards page (or falls back independently)
      - search returns home; articles reads from home (no rewards page visit)

    Recheck pass mirrors the same hand-off pattern for 1 more rewards page visit.
    Total rewards page visits: 2 (initial + recheck).
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

        # ── Initial pass ───────────────────────────────────────────
        # daily opens rewards page, parses earn values, stays on it
        daily_result = _run_daily(d)
        result["daily"] = daily_result

        if daily_result is not None and daily_result.get("current_points") is None:
            result["errors"].append("Could not read current points balance")

        search_earn_y, read_earn_remaining = _extract_earn_values(daily_result)

        # search picks up from rewards page (or opens its own if daily failed)
        result["search"] = _run_search(d, search_earn_y=search_earn_y)

        # articles starts from home (search returned home at end of its run)
        result["articles"] = _run_articles(d, read_earn_remaining=read_earn_remaining)

        # ── Recheck pass ───────────────────────────────────────────
        _recheck_on_device(d, result)

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
    device_names: optional dict mapping serial -> friendly name, provided by
    a launcher script. When None (direct run), labels fall back to EMU-N/total format.
    """
    if device_names is None:
        device_names = {}
    run_start = datetime.now()
    print()
    print("=" * 52)
    print("        BING AUTOMATION — STARTING UP             ")
    print("=" * 52)

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
        name  = device_names.get(s, "")
        label = f"{name}" if name else s
        print(f"    {i}. {label} ({s})")
    print(f"  Max parallel  : {MAX_WORKERS}")
    print("=" * 52)
    print()

    device_args = [
        (serial, index, total, device_names.get(serial, ""))
        for index, serial in enumerate(serials, start=1)
    ]

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = list(executor.map(_run_on_device, device_args))
    except KeyboardInterrupt:
        pass
    else:
        print()
        print("=" * 52)
        print("  All devices finished.")
        print("=" * 52)

        _print_summary(results)
        _save_summary(results, run_start)


if __name__ == "__main__":
    main()