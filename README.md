# Bing Automation

A fully automated Python tool that controls the Microsoft Bing mobile app to complete daily rewards, read articles, and perform searches. Automatically detects all connected Android devices and runs tasks in parallel.

## Features

- **Fully Automated** — No menus or input required. Just run and it handles everything.

- **Three Complete Tasks**
  - **Daily Rewards** — Check-in, Daily Set cards (3 × 10 points), More Activities (1 × 5 points)
  - **Read Articles** — Auto-reads unique articles from Bing home feed with duplicate prevention
  - **Search to Earn** — Performs realistic searches using Wikipedia article titles

- **Multi-Device Parallel Execution** — Auto-detects all ADB devices and runs tasks simultaneously (respects `MAX_WORKERS` limit)

- **Smart Navigation & Recovery** — Detects if you're outside Bing, in wrong screen, or genuinely stuck, and recovers appropriately

- **Wikipedia Integration** — Fetches real Wikipedia article titles for authentic search queries; intelligent fallback to generated queries if Wikipedia unavailable

- **Thread-Safe Logging** — Synchronized output from multiple devices running in parallel with device labels for clarity

## Requirements

### Hardware
- Android device or emulator connected via USB
- ADB (Android Debug Bridge) enabled and configured
- Minimum Android version: 5.0+ (typical for Bing mobile app)

### Software
- Python 3.7+
- **ADB (Android Debug Bridge)** — Download from: https://developer.android.com/studio/releases/platform-tools
  - Windows: Extract to a folder (e.g., `C:\platform-tools`) and add to PATH
  - Mac/Linux: Install via `brew install android-platform-tools` or package manager
- `uiautomator2` — Python bindings for Android UIAutomator
- Microsoft Bing mobile app (installed on target device)

### Connection Setup
- ADB connection address: `127.0.0.1:7555` (configurable in `config.py`)
- Device must be in Developer Mode with USB Debugging enabled
- If using emulator: start with adb connection before running the script

### Tested Configurations

**Verified Compatible:**
- **Emulator:** MuMu Emulator (Android emulator for Windows)
- **Devices:** Samsung Galaxy A52s 5G, Samsung Galaxy A53 5G
- **Screen Size:** Optimized for 900×1600 (standard phone portrait)

**Screen Responsiveness:**
The script adapts to different screen resolutions through dynamic coordinate scaling. While tested and responsive on various sizes, optimal performance is guaranteed on the above configurations. If using other devices, minor UI element timing adjustments in `config.py` may be needed.

⚠️ **Note:** Bing's UI layout varies by device model and app version. If you encounter "element not found" errors, update your resource IDs using the UIAutomator Dump method in the Troubleshooting section.

## Installation

1. **Clone/download the project**
   ```bash
   cd bing-automation
   ```

2. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Enable ADB on Your Device(s)**
   - Go to Settings → About Phone
   - Tap Build Number 7 times to enable Developer Mode
   - Go to Settings → Developer Options → Enable USB Debugging
   - Connect device via USB to your computer

4. **Verify ADB Connection**
   ```bash
   adb devices
   ```
   You should see your device(s) listed as `device`. If using emulators, they typically connect automatically.

## Usage

### Running the Program

```bash
python main.py
```

The script will:
1. Auto-detect all connected ADB devices
2. Launch Bing on each device
3. Run all three tasks in sequence on each device (in parallel if multiple devices)
4. Clean up (close tabs) and finish

### Workflow Summary

**Per Device:**
1. **Task 1: Daily Rewards** (~2–3 min)
   - Opens Rewards page
   - Attempts daily check-in (skipped if streaks not visible today)
   - Collects 3 Daily Set cards
   - Collects 1 More Activities card
   - Returns to home

2. **Task 2: Read Articles** (~2 min)
   - Scrolls to article feed
   - Reads 10–12 articles (randomized)
   - Holds each article for 7–9.5 seconds
   - Tracks seen articles to avoid duplicates
   - Returns to home

3. **Task 3: Search to Earn** (~5–8 min)
   - Opens Rewards page
   - Scrolls to "Search to Earn" section
   - Performs 8–12 searches (randomized)
   - Uses Wikipedia article titles for realistic queries
   - Holds results page for 7–9 seconds per search
   - Returns to home

**Total per device:** ~10–15 minutes (includes all overhead)

## Configuration

All settings are in [config.py](config.py). Key tweaks:

### Parallelism
```python
MAX_WORKERS = 2  # Max devices running simultaneously
CONNECT_RETRIES = 3  # Connection attempts per device
CONNECT_RETRY_WAIT = 10  # Seconds between retries
```

### Timing (seconds)
```python
BACK_WAIT = 2.5  # Pause after back button
REWARDS_READ_WAIT_MIN = 4
REWARDS_READ_WAIT_MAX = 6.5  # Hold time per reward card
LAUNCH_SETTLE_WAIT = 5  # Wait after Bing foreground for UI to render
```

### Search Limits
```python
SEARCH_HOLD_MIN = 7
SEARCH_HOLD_MAX = 9  # Seconds to hold results page
SEARCH_WAIT_MIN = 11
SEARCH_WAIT_MAX = 17  # Seconds between searches
MAX_SCROLL_ATTEMPTS = 4  # Max attempts to find "Search to Earn"
```

### Retry Limits
```python
MAX_MISSES = 3  # Max consecutive UI element misses before scrolling
MAX_FAILS = 3   # Max consecutive failures before aborting article loop
```

### Article Randomization
```python
ARTICLE_COUNT_MIN = 10
ARTICLE_COUNT_MAX = 12  # Random articles to read per run
ARTICLE_DURATION_MIN = 7
ARTICLE_DURATION_MAX = 9.5  # Seconds per article (randomized)
```

## Project Structure

```
bing-automation/
├── main.py                 # Entry point (auto-detect & parallel execution)
├── config.py               # All configuration constants in one place
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── core/
│   ├── __init__.py
│   └── device.py           # Device connection, ADB, logging, navigation
└── tasks/
    ├── __init__.py
    ├── daily.py            # Daily Rewards (check-in, cards)
    ├── articles.py         # Article reading with duplicate tracking
    ├── search.py           # Search to Earn automation
    └── queries.py          # Wikipedia query fetcher + fallback combinator
```

## Architecture

### Main Entry Point

**`main.py`**
- Detects all connected ADB devices (with auto-restart recovery)
- Spawns thread pool with `MAX_WORKERS` parallel workers
- Each thread runs the full 3-task sequence independently
- Thread-safe logging with device labels
- Connection retry logic with configurable retries

### Core Components

**`core/device.py`** — Device & Navigation
- `detect_devices()` — Auto-detect via `adb devices` (with server restart fallback)
- `connect(serial)` — Establish uiautomator2 connection
- `launch_bing(d)`, `ensure_home_screen(d)`, `go_back_to_home(d)` — Navigation
- `dismiss_popup(d)` — Detect & dismiss blocking dialogs
- `close_all_tabs(d)` — Cleanup after tasks
- `log(msg)` — Thread-safe timestamped logging

**`tasks/daily.py`** — Daily Rewards
- `open_rewards_page(d)` — Tap Rewards card
- `do_checkin(d)` — Daily streak check-in (outcomes: skipped/attempted/done)
- `collect_cards(d, keyword, count, label)` — Click & hold reward cards with recovery

**`tasks/articles.py`** — Article Reading
- `scroll_to_articles(d)` — Skip header to reach feed
- `read_articles(d, count, duration)` — Process unique articles with `seen_titles` tracking
- 3-branch recovery: outside Bing / wrong room / feed exhausted

**`tasks/search.py`** — Search to Earn
- `_scroll_to_search_earn(d)` — Find "Search to Earn" row
- `_do_single_search(d, query)` — Type query, hold results, return
- 3-branch recovery + overlay management

**`tasks/queries.py`** — Query Generation
- `get_queries(count)` — Try Wikipedia API first; fallback to combinator
- Wikipedia: Real article titles (45K+ unique combinations via topic + modifier + prefix)

### Key Design Patterns

- **3-Branch Recovery** — Each task detects location (outside Bing / wrong room / right room) and recovers accordingly
- **Dynamic Geometry** — All coordinates scale to device resolution
- **Safe Zones** — Interactions restricted to 15%–85% vertical range
- **Duplicate Prevention** — Article titles hashed; searches use varied sources
- **Parallel-Safe** — Thread-local logging, independent device connections

## Logging & Output

All operations are logged with timestamps and device labels (for multi-device clarity):

```
[14:32:15] [EMU-1] Connecting...
[14:32:15] [EMU-2] Connecting...
[14:32:16] [EMU-1]   Device: emulator (1440x3120)
[14:32:16] [EMU-2]   Device: emulator (1440x3120)
[14:32:17] [EMU-1] [STARTUP] Launching Bing...
[14:32:17] [EMU-2] [STARTUP] Launching Bing...
[14:32:19] [EMU-1]   Bing foreground confirmed ✓
[14:32:19] [EMU-2]   Bing foreground confirmed ✓
[14:32:20] [EMU-1] TASK 1/3 — Daily Rewards
[14:32:20] [EMU-2] TASK 1/3 — Daily Rewards
...
[14:35:22] [EMU-1] Device run complete ✓
[14:35:25] [EMU-2] Device run complete ✓
```

## Troubleshooting

### Connection Issues
**Problem:** `[FAIL] Bing did not reach foreground within 30s`
- **Solution:** Verify Bing is installed: `adb shell pm list packages | findstr bing`
- **Solution:** Check ADB address in `config.py` matches actual device connection
- **Solution:** Manually tap Bing icon on device and try again

### UI Element Not Found
**Problem:** `[!] Rewards card not found` or `[!] No feed items found`
- **Solution:** Bing UI may have changed; verify resource IDs using UIAutomator Dump:
  ```bash
  adb shell uiautomator dump /sdcard/dump.xml
  adb pull /sdcard/dump.xml
  ```
- **Solution:** Increase `REWARDS_PAGE_TIMEOUT` or `MAX_MISSES` in `config.py`
- **Solution:** Manually navigate to the page and ensure it loads before retrying

### Articles Not Reading
**Problem:** Script scrolls but doesn't read articles
- **Solution:** Ensure article feed is visible and not in collapsed state
- **Solution:** Increase `DEFAULT_ARTICLE_DURATION` to allow more time per article
- **Solution:** Check if streaks/check-in modal is blocking feed (close manually, restart)

### ADB Connection Failed
**Problem:** `uiautomator2.exceptions.ConnectError`
- **Solution:** Verify device is connected: `adb devices`
- **Solution:** Restart ADB daemon: `adb kill-server && adb start-server`
- **Solution:** Try connecting manually: `adb connect 127.0.0.1:7555`

## Performance Notes

- **Daily Rewards Task:** ~2–3 minutes depending on card visibility
- **Article Reading Task:** ~2 minutes for default 10–12 articles at 7–9.5 seconds each
- **Search to Earn Task:** ~5–8 minutes for 8–12 searches using Wikipedia queries
- **All Three Tasks:** ~10–15 minutes total per device (includes navigation overhead)
- **Network Delay:** Points registration may take 1–2 seconds; holding times are randomized per `config.py`

## Limitations & Known Issues

1. **Streaks Variable Availability** — Bing shows streaks inconsistently; check-in is skipped if not visible today
2. **WebView Rendering** — Rewards page elements may take time to render; timeouts are configurable
3. **Portrait Orientation** — Safe interaction zones assume portrait (landscape may need adjustment)
4. **Wikipedia Availability** — If Wikipedia is down, queries fall back to combinator (prefix + topics + modifiers)
6. **Emulator Lag** — Slow emulators may timeout; increase timeouts in `config.py` if needed

## Dependencies

All listed in [requirements.txt](requirements.txt):
- **uiautomator2** — Android UIAutomator bindings for Python
- **requests** — HTTP library (for Wikipedia queries)
- **adbutils** — ADB utilities for device management
- **pillow**, **lxml**, **decorator** — Supporting libraries

## Disclaimer

This tool is for personal use with your own Bing account. Ensure compliance with Microsoft's Terms of Service. I am not responsible for any account restrictions or bans resulting from automated interactions.
