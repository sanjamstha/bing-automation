# config.py — All project-wide constants in one place

# ── Device connection ──────────────────────────────────────────────
ADB_ADDRESS = "127.0.0.1:7555"

# ── Bing app identifiers ───────────────────────────────────────────
BING_PACKAGE  = "com.microsoft.bing"
HOME_ACTIVITY = "com.microsoft.sapphire.app.main.MainSapphireActivity"

# ── Rewards page identifiers ───────────────────────────────────────
REWARDS_CARD_ID    = "com.microsoft.bing:id/glance_card_container"
REWARDS_CARD_TITLE = "com.microsoft.bing:id/tv_glance_card_title"
REWARDS_CARD_DESC  = "Rewards"
BACK_BTN_ID        = "com.microsoft.bing:id/sa_template_header_action_back"

# ── Article feed identifier ────────────────────────────────────────
ARTICLE_RESOURCE_ID    = "com.microsoft.bing:id/sa_hp_native_list_item_container"
ARTICLE_SCROLL_VIEW_ID = "com.microsoft.bing:id/sa_home_scroll_view_nested"

# ── Check-in text tokens ───────────────────────────────────────────
TEXT_STREAKS = "Streaks"
TEXT_CHECKIN = "Check in"

# ── Timing (seconds) ──────────────────────────────────────────────
BACK_WAIT            = 2.5  # Pause after pressing back
REWARDS_READ_WAIT    = 5    # Hold time per reward card to register points
REWARDS_PAGE_TIMEOUT = 15   # Max wait for Rewards WebView to load
LAUNCH_SETTLE_WAIT   = 3    # Wait after Bing reaches foreground for UI to render
HOME_SETTLE_WAIT     = 2    # Wait after home screen confirmed for widgets to draw

# ── Popup detection & dismissal ────────────────────────────────────
POPUP_CONTAINER_ID = "android:id/parentPanel"               # Generic Android dialog wrapper
POPUP_CLOSE_ID     = "com.microsoft.bing:id/do_you_like_close"  # Bing feedback popup close btn

# ── Retry limits ──────────────────────────────────────────────────
MAX_MISSES     = 3   # Max consecutive misses before giving up on reward cards
MAX_FAILS      = 3   # Max consecutive failures before aborting article read loop

# ── Article reader defaults ────────────────────────────────────────
DEFAULT_ARTICLE_COUNT    = 11
DEFAULT_ARTICLE_DURATION = 7   # seconds per article