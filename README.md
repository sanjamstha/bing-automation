# Bing Automation

A Python automation tool for the Microsoft Bing mobile app that automates daily rewards collection and article reading tasks.

## Features

- **Daily Rewards Automation**
  - Daily check-in with streak tracking
  - Daily Set collection (3 cards × 10 points each)
  - More Activities collection (1 card × 5 points)
  - Automatic point registration and return to home screen

- **Article Reading Automation**
  - Reads articles from the Bing home feed
  - Configurable article count and read duration
  - Intelligent duplicate detection via title hashing
  - Dynamic scaling to any device screen resolution
  - Safe interaction zones to avoid accidental taps

- **Smart Device Navigation**
  - Cold-start Bing from Android home screen
  - Verifies correct screen/activity before executing tasks
  - Reliable back navigation using in-app buttons
  - Automatic retry logic with configurable limits

- **Combined Execution Mode**
  - Run both tasks sequentially in one session
  - Optimized workflow: Daily Rewards → Read Articles → Return Home

## Requirements

### Hardware
- Android device or emulator connected via USB
- ADB (Android Debug Bridge) enabled and configured
- Minimum Android version: 5.0+ (typical for Bing mobile app)

### Software
- Python 3.7+
- `uiautomator2` — Python bindings for Android UIAutomator
- Microsoft Bing mobile app (installed on target device)

### Connection Setup
- ADB connection address: `127.0.0.1:7555` (configurable in `config.py`)
- Device must be in Developer Mode with USB Debugging enabled
- If using emulator: start with adb connection before running the script

## Installation

1. **Clone/download the project**
   ```bash
   cd bingAutomation
   ```

2. **Install Python dependencies**
   ```bash
   pip install uiautomator2
   ```

3. **Enable ADB on your Android device**
   - Go to Settings → About Phone
   - Tap Build Number 7 times to enable Developer Mode
   - Go to Settings → Developer Options
   - Enable USB Debugging
   - Connect device via USB to computer

4. **Start ADB connection** (if not using emulator)
   ```bash
   adb connect 127.0.0.1:7555
   ```

## Usage

### Running the Program

Start the automation from the project root directory:

```bash
python main.py
```

### Main Menu Options

```
1 — Daily Rewards      (Check-in + Daily Set + More Activities)
2 — Read Articles      (Read N articles for D seconds each)
3 — Both               (Daily Rewards → Read Articles)
0 — Exit               (Quit the program)
```

### Example Workflows

**Option 1: Daily Rewards Only**
- Opens Bing Rewards page
- Attempts daily check-in (if streaks section is available)
- Collects 3 Daily Set cards (10 points each)
- Collects 1 More Activities card (5 points)
- Total: up to 35 points per day

**Option 2: Read Articles Only**
- Scrolls to the article feed
- Reads 11 articles (default) at 7 seconds each (default)
- Tracks read articles to avoid re-reading
- Total: ~77 seconds for default settings

**Option 3: Both Tasks**
- Runs Daily Rewards workflow first
- Then runs article reading workflow
- Total: ~3 minutes for default settings

## Configuration

Edit `config.py` to customize behavior:

### Device Connection
```python
ADB_ADDRESS = "127.0.0.1:7555"  # ADB connection address
```

### UI Element Identifiers
```python
BING_PACKAGE  = "com.microsoft.bing"
HOME_ACTIVITY = "com.microsoft.sapphire.app.main.MainSapphireActivity"
REWARDS_CARD_ID = "com.microsoft.bing:id/glance_card_container"
ARTICLE_RESOURCE_ID = "com.microsoft.bing:id/sa_hp_native_list_item_container"
```

### Timing (in seconds)
```python
BACK_WAIT            = 2.5    # Pause after pressing back
REWARDS_READ_WAIT    = 4      # Hold time per reward card to register points
REWARDS_PAGE_TIMEOUT = 15     # Max wait for Rewards page to load
```

### Retry Limits
```python
MAX_MISSES = 3  # Max consecutive UI element misses before scrolling
MAX_FAILS  = 5  # Max consecutive failures before aborting article loop
```

### Article Reader Defaults
```python
DEFAULT_ARTICLE_COUNT    = 11  # Number of articles to read
DEFAULT_ARTICLE_DURATION = 7   # Seconds per article
```

## Project Structure

```
bingAutomation/
├── main.py                 # Entry point with menu system
├── config.py               # Centralized configuration constants
├── README.md               # This file
├── initialREADME.md        # Original README
├── core/
│   ├── __init__.py
│   └── device.py           # Device connection & navigation helpers
└── tasks/
    ├── __init__.py
    ├── daily.py            # Daily Rewards automation
    └── articles.py         # Article reading automation
```

## Architecture

### Core Components

**`core/device.py`** — Device Management
- `connect()` — Establish ADB connection and return device handle
- `launch_bing(d)` — Cold-start Bing app from home screen
- `ensure_home_screen(d)` — Verify correct activity, force-launch if needed
- `go_back_to_home(d)` — Navigate back via in-app button or system key
- `log(msg)` — Timestamped logging utility

**`tasks/daily.py`** — Daily Rewards Workflow
- `open_rewards_page(d)` — Tap Rewards card to open page
- `wait_for_rewards_page(d)` — Poll for Rewards page landmarks
- `do_checkin(d)` — Perform daily check-in with outcome tracking
- `collect_cards(d, keyword, count, label)` — Click and hold reward cards
- `run(d)` — Main task orchestrator
- `print_report(result)` — Summary report printer

**`tasks/articles.py`** — Article Reading Workflow
- `scroll_to_articles(d)` — Skip header banners to reach feed
- `read_articles(d, count, duration)` — Process unique articles in feed
- `run(d, limit, duration)` — Main task orchestrator
- `print_report(result)` — Summary report printer

### Key Techniques

- **Dynamic Geometry Scaling** — All swipe coordinates and safe zones scale to device resolution
- **Duplicate Detection** — Article titles hashed in `seen_titles` set to avoid re-reading
- **Safe Interaction Zones** — Clicks only on UI elements within screen margins (15%–85%)
- **Retry Logic** — Automatic scrolling and retry when expected elements not found
- **Activity Verification** — Ensures correct screen before task execution

## Logging

All operations are logged with timestamps. Example output:

```
[14:32:15] Connecting...
[14:32:16]   Device: Samsung Galaxy S21 (1440x3120)
[14:32:17] [STARTUP] Launching Bing...
[14:32:19]   Bing foreground confirmed ✓
[14:32:20] [1/3] Opening Rewards page...
[14:32:21]   Tapping Rewards card...
[14:32:23]   Waiting for Rewards page (up to 15s)...
[14:32:25]   Rewards page loaded ✓
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
- **Article Reading Task:** ~2 minutes for default 11 articles at 7 seconds each
- **Both Tasks:** ~5–6 minutes total (includes navigation overhead)
- **Network Delay:** Points registration may take 1–2 seconds; holding time is `REWARDS_READ_WAIT`

## Limitations & Known Issues

1. **Streaks Section Variable Availability** — The Bing app shows streaks inconsistently; check-in is skipped if not visible
2. **Article Duplicate Titles** — Articles with identical titles are treated as duplicates and skipped
3. **WebView Element Instability** — Rewards page elements may take time to render; timeouts are configurable
4. **Dynamic Layout** — Safe interaction zones assume portrait orientation; landscape may require adjustment
5. **Single Device** — Script controls one device at a time (no multi-device support)

## Future Enhancements

- Support for user-prompted article count/duration at runtime
- Logging to file with rotation
- Session persistence (resume interrupted tasks)
- Multi-device support
- Automated Bing UI element discovery via accessibility service
- Web UI for scheduling and monitoring

## Dependencies

- **uiautomator2** — Python bindings for Android UIAutomator framework
  - Provides `connect()`, device element queries, swipe/click actions, activity verification
  - GitHub: https://github.com/openatx/uiautomator2

## License

This project is provided as-is for personal automation use with the Bing mobile app.

## Disclaimer

This automation tool is intended for personal use with your own Bing account. Ensure compliance with Microsoft's Terms of Service and any applicable app usage policies. The maintainers are not responsible for account suspension or other consequences of automated interaction.

---

**Questions or Issues?** Check the Troubleshooting section or review the inline code comments in each module.
