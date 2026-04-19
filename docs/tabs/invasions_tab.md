# tabs/invasions_tab.py

## Purpose

Real-time invasion tracker that polls TTR's public invasions API every 60 seconds and displays currently active cog invasions as themed cards. New in v2.

---

## Classes

### `InvasionsWorker` (threading.Thread)

Background thread that fetches `https://www.toontownrewritten.com/api/invasions` and calls a callback with the results. Uses `urllib` (stdlib) rather than `requests` to avoid adding a dependency.

#### `run()`

`urllib.request.urlopen()` with a 10-second timeout. On success: parses JSON and calls `callback(data["invasions"], None)`. On any error: calls `callback(None, str(error))`.

The `"invasions"` key in the API response is a dict of `{district: {type, progress, ...}}`.

---

### `InvasionsTab` (QWidget)

#### `__init__`

Creates a QTimer firing every 60,000ms (1 minute) connected to `fetch_invasions()`. Fetches immediately on init (doesn't wait for first timer tick).

#### `fetch_invasions()`

Starts an `InvasionsWorker` thread. The callback uses `Signal` to safely deliver results to the main thread.

#### `_on_invasions_updated(invasions, error)`

Main-thread slot. If error: shows error message. If no invasions: calls `_show_empty_state()`. Otherwise: clears the scroll area and calls `_create_invasion_card()` for each active invasion.

#### `_show_empty_state()`

Displays a centered "No active invasions" message with muted text styling.

#### `_create_invasion_card(district, details)` → QWidget

Builds a card widget for one invasion:
- **Top row**: Department badge (colored pill with cog type name), cog name, progress text (`"current/max"`)
- **Progress bar**: Rendered if `progress` can be split into `current/max` integers. Uses `SmoothProgressBar` from `theme_manager`.
- **Bottom row**: District name, elapsed time in minutes (`"X min ago"` from timestamp)

**Department colors:**
| Department | Color |
|-----------|-------|
| Sellbot | `#E05252` (red) |
| Cashbot | `#56B8E8` (blue) |
| Lawbot | `#9B6BE0` (purple) |
| Bossbot | `#4CB960` (green) |
| Boardbot | `#8B6948` (brown) |

Department is determined by matching the cog type string against known keywords.

#### `build_ui()`

Header: title label + auto-refresh status + manual refresh button.
Body: `QScrollArea` containing a vertical layout of invasion cards.

#### `refresh_theme()`

Re-styles all card labels and progress bars using current theme colors.

---

## Dependencies

| Module | Used for |
|--------|----------|
| `utils/theme_manager.py` | Colors, `SmoothProgressBar` |
| `urllib.request` | API fetch (stdlib) |
| `json`, `threading`, `time` | Response parsing, background fetch |

---

## Known Issues / Technical Debt

- Cards are rebuilt from scratch on every poll (60s). A diff-and-update approach would be more efficient but given the small card count this is negligible.
- The `refresh_theme()` approach doesn't rebuild cards — it styles existing ones — so cards created before a theme change may have slightly different styles than new ones until the next poll.
- The 60-second interval is hardcoded. A user-configurable refresh rate could be useful.
- Boardbot invasions are mapped to brown (`#8B6948`) — Boardbot is a CC-exclusive faction, so this color is only relevant if TTR API ever includes CC data (it doesn't currently).
