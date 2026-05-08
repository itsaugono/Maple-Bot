# MapleStory-Py — Phase 1: Window Capture & Data Extraction

## Overview
Build a Python tool that captures the MapleStory game window in the background,
extracts game state data via OpenCV + Tesseract OCR, and displays it in a
DearPyGui interface.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  CaptureThread (daemon)                         │
│  - Finds/captures MapleStory window @ 1366x768  │
│  - Runs mss/win32gui grab loop                  │
│  - Pushes frames to shared buffer (thread-safe) │
└────────────────────┬────────────────────────────┘
                     │ threading.Lock
┌────────────────────▼────────────────────────────┐
│  MapProcessor                                    │
│  - Minimap extraction (crop known region)        │
│  - Template matching (player dot, portals)       │
│  - HP/MP/EXP bar pixel sensing + Tesseract OCR   │
└────────────────────┬────────────────────────────
                     │ GameState dataclass
────────────────────▼────────────────────────────┐
│  DearPyGui UI                                    │
│  - dynamic_texture updates (minimap + live feed) │
│  - Status line: resolution, coords, HP/MP, EXP   │
│  - Tab bar: Minimap | Live Capture               │
└─────────────────────────────────────────────────┘
```

---

## File Structure

```
maplestory-py/
├── main.py              # Entry point, starts UI + capture thread
├── capture.py           # CaptureThread class (window find + grab loop)
├── processor.py         # MapProcessor class (CV + OCR logic)
├── ui.py                # DearPyGui layout & texture management
── config.py            # Constants (regions, thresholds, colors)
├── requirements.txt     # Dependencies
└── plan.md              # This file
```

---

## Module Details

### 1. `capture.py` — Window Selection & Capture

| Responsibility | Details |
|---|---|
| Find window | `win32gui.FindWindow(None, "MapleStory")` with pygetwindow fallback |
| Background grab | `mss` screen capture targeting the window rect |
| Target resolution | 1366×768; scale if actual differs |
| Threading | `threading.Thread(daemon=True)` running at ~60 FPS |
| Shared state | `threading.Lock` protecting a NumPy frame buffer |

Key class:
```python
class CaptureThread(threading.Thread):
    def __init__(self, target_fps=60):
        ...
    def select_window(self, title="MapleStory") -> bool: ...
    def get_frame(self) -> np.ndarray | None: ...  # thread-safe copy
    def run(self): ...  # capture loop
    def stop(self): ...
```

### 2. `processor.py` — CV Logic (MapProcessor)

| Task | Approach |
|---|---|
| Minimap extraction | Crop fixed region (top-left ~229×71 based on reference) |
| Player detection | Template match yellow dot on minimap (small 5×5 template) |
| Portal detection | Template match portal icons on minimap |
| HP/MP reading | Pixel-ratio scan of bar region + Tesseract OCR on numeric text |
| EXP reading | Pixel-ratio scan of EXP bar + Tesseract OCR on percentage text |
| PState detection | Check player vertical velocity / ground pixel below character |

Key classes:
```python
@dataclass
class GameState:
    player_pos: tuple[int, int]
    target_pos: tuple[int, int]
    pstate: str            # "Grounded", "Airborne", etc.
    hp_pct: float
    mp_pct: float
    exp_pct: float
    portal_count: int
    others_count: int
    minimap_size: tuple[int, int]

class MapProcessor:
    def __init__(self, config: dict): ...
    def process_frame(self, frame: np.ndarray) -> GameState: ...
    def extract_minimap(self, frame: np.ndarray) -> np.ndarray: ...
    def find_player(self, minimap: np.ndarray) -> tuple[int,int]: ...
    def find_portals(self, minimap: np.ndarray) -> list[tuple[int,int]]: ...
    def read_hp_mp(self, frame: np.ndarray) -> tuple[float, float]: ...
    def read_exp(self, frame: np.ndarray) -> float: ...
    def ocr_bar_text(self, roi: np.ndarray) -> str: ...  # Tesseract helper
```

### 3. `ui.py` — DearPyGui Interface

Layout (matches reference image):
- **Capture collapsing header**
  - "Select Window" button
  - Status text: `[●] CAPTURING (XX.X FPS)`
  - Info lines: Window res, Minimap size, Player/Target coords, PState, HP/MP%, EXP%
- **Tab Bar**
  - `Minimap` tab → `dpg.add_image()` bound to minimap dynamic texture
  - `Live Capture` tab → `dpg.add_image()` bound to full-frame dynamic texture

Texture management:
```python
with dpg.texture_registry():
    live_texture = dpg.add_dynamic_texture(width, height, default_data)
    minimap_texture = dpg.add_dynamic_texture(mm_w, mm_h, default_data)

# In render callback (called each frame):
dpg.set_value(live_texture, frame_rgba_flat)
dpg.set_value(minimap_texture, minimap_rgba_flat)
```

### 4. `config.py` — Constants

```python
WINDOW_TITLE = "MapleStory"
TARGET_RES = (1366, 768)
CAPTURE_FPS = 60

# Minimap region (x, y, w, h) at 1366x768
MINIMAP_REGION = (8, 25, 229, 71)

# HP/MP bar regions (x, y, w, h)
HP_BAR_REGION = (...)
MP_BAR_REGION = (...)
EXP_BAR_REGION = (...)

# Template colors (HSV ranges)
PLAYER_DOT_COLOR = (...)  # Yellow
PORTAL_COLOR = (...)

# Tesseract config
TESSERACT_LANG = "eng"
TESSERACT_CONFIG = r"--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.%/"
```

---

## Dependencies (`requirements.txt`)

```
dearpygui>=1.9
opencv-python>=4.8
numpy
mss
pywin32
pygetwindow
pytesseract
```

Note: Tesseract OCR engine must be installed separately on the system.
- Windows: https://github.com/UB-Mannheim/tesseract/wiki
- Add `tesseract.exe` to PATH or set `pytesseract.pytesseract.tesseract_cmd`

---

## Performance Considerations

1. **Thread safety**: Use `threading.Lock` for frame buffer; UI only reads a copy.
2. **Memory**: Reuse pre-allocated NumPy arrays; flatten to RGBA for DPG textures in-place.
3. **FPS**: Capture thread sleeps `1/target_fps - elapsed` each iteration.
4. **Texture updates**: Only call `dpg.set_value()` when a new frame is available (dirty flag).
5. **OCR throttling**: Run Tesseract at a lower frequency (e.g., every 10 frames) since HUD text changes slowly.
6. **No unnecessary copies**: Pass array views where possible; only copy when crossing thread boundaries.

---

## Implementation Order

1. [ ] Set up project structure and dependencies
2. [ ] Implement `CaptureThread` with window selection + mss grab
3. [ ] Build DearPyGui layout (static, with placeholder textures)
4. [ ] Wire capture thread → dynamic texture updates (Live Capture tab)
5. [ ] Implement `MapProcessor.extract_minimap()` + display in Minimap tab
6. [ ] Implement player/portal template matching on minimap
7. [ ] Implement HP/MP/EXP bar pixel reading + Tesseract OCR integration
8. [ ] Wire all GameState fields to UI status text
9. [ ] Performance tuning (FPS cap, dirty flags, buffer reuse, OCR throttling)
