# config.py — All project-wide constants in one place

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
LAUNCH_SETTLE_WAIT   = 5    # Wait after Bing reaches foreground for UI to render
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

# ── Tab management identifiers ─────────────────────────────────────
# Navbar (persistent across all screens — Compose view, no resource-ids on items)
NAV_TABS_DESC       = "Tabs"              # content-desc of the Tabs navbar button
NAV_HOME_DESC       = "Home"             # content-desc of the Home navbar button
 
# Tab switcher screen
TABS_TITLE_ID       = "com.microsoft.bing:id/sa_tabs_title"        # heading — confirms switcher open
TABS_MORE_BTN_ID    = "com.microsoft.bing:id/sa_tabs_more"         # 3-dot More button (top-right)
 
# Bottom-sheet menu (appears after tapping More)
TABS_ACTION_LIST_ID = "com.microsoft.bing:id/sa_action_recycle_view"  # confirms sheet is open
TABS_CLOSE_ALL_DESC = "Close all tabs, Button"  # content-desc of the clickable row
 
# ── Tab management timing (seconds) ───────────────────────────────
TAB_NAV_WAIT        = 2.0  # settle wait after each navbar / sheet tap
TAB_SWITCHER_TIMEOUT = 8   # max wait for tab switcher title to appear

# ── Concurrency ────────────────────────────────────────────────────
MAX_WORKERS = 2  # Max devices running simultaneously.