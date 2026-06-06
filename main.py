"""
main.py — Bing Automation: Unified Entry Point

Menu options:
  1 — Daily Rewards  (Check-in + Daily Set + More Activities)
  2 — Read Articles
  3 — Both           (Daily Rewards first, then Read Articles)
  0 — Exit
"""

from core.device import connect, launch_bing, ensure_home_screen, dismiss_popup, log
from tasks import daily, articles


# ── Menu ───────────────────────────────────────────────────────────

def print_menu():
    print()
    print("=" * 52)
    print("        BING AUTOMATION — MAIN MENU               ")
    print("=" * 52)
    print("  1  —  Daily Rewards")
    print("  2  —  Read Articles")
    print("  3  —  Both (Daily Rewards → Read Articles)")
    print("  0  —  Exit")
    print("=" * 52)


def get_choice():
    while True:
        choice = input("Select an option [0-3]: ").strip()
        if choice in ("0", "1", "2", "3"):
            return choice
        print("  [!] Invalid choice — please enter 0, 1, 2, or 3.")


# ── Startup helpers ────────────────────────────────────────────────

def _startup(d):
    """
    Shared startup sequence: launch Bing and confirm the home screen.
    Returns True on success, False if either step fails.
    """
    log("\n[STARTUP] Launching Bing...")
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


# ── Task runners ───────────────────────────────────────────────────

def run_daily(d):
    result = daily.run(d)
    daily.print_report(result)


def run_articles(d):
    
    result = articles.run(d)
    articles.print_report(result)


def run_both(d):

    # 1. Daily Rewards
    log("\n" + "─" * 52)
    log("TASK 1/2 — Daily Rewards")
    log("─" * 52)
    daily_result = daily.run(d)
    daily.print_report(daily_result)

    # 2. Read Articles (device is already on home screen after daily.run)
    log("\n" + "─" * 52)
    log("TASK 2/2 — Read Articles")
    log("─" * 52)
    articles_result = articles.run(d)
    articles.print_report(articles_result)


# ── Main ───────────────────────────────────────────────────────────

def main():
    print_menu()
    choice = get_choice()

    if choice == "0":
        print("Exiting. Goodbye!")
        return

    # Connect once; all tasks share the same device handle
    d = connect()

    if not _startup(d):
        return

    if choice == "1":
        run_daily(d)
    elif choice == "2":
        run_articles(d)
    elif choice == "3":
        run_both(d)

    log("\nAll tasks complete.")


if __name__ == "__main__":
    main()