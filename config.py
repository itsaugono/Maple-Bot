WINDOW_TITLE = "MapleStory"
TARGET_RES = (1366, 768)
CAPTURE_FPS = 60

MINIMAP_REGION = (8, 25, 229, 71)

HP_BAR_REGION = (0, 0, 0, 0)
MP_BAR_REGION = (0, 0, 0, 0)
EXP_BAR_REGION = (0, 0, 0, 0)

PLAYER_DOT_COLOR_LOW = (20, 100, 100)
PLAYER_DOT_COLOR_HIGH = (35, 255, 255)
PORTAL_COLOR_LOW = (100, 50, 50)
PORTAL_COLOR_HIGH = (140, 255, 255)

TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSERACT_LANG = "eng"
TESSERACT_CONFIG = r"--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.%/"
HPMP_OCR_CONFIG = r"--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789/,"
EXP_OCR_CONFIG = r"--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.%[],"

OCR_THROTTLE_FRAMES = 10

TEMPLATES_DIR = "templates"
TEMPLATES_CONFIG = "templates/config.json"
MATCH_THRESHOLD = 0.75

# Resolution presets: templates folder, fallback minimap region, bar offsets
RESOLUTION_PRESETS = {
    "1366x768": {
        "res": (1366, 768),
        "template_folder": "templates/768",
        "minimap_region": (8, 25, 229, 71),
        "hp_bar_offset": {"x_offset": -75, "y_from_bottom": 46, "width": 150, "height": 14},
        "mp_bar_offset": {"x_offset": -75, "y_from_bottom": 29, "width": 150, "height": 14},
        "exp_bar_offset": {"x_offset": -150, "y_from_bottom": 12, "width": 300, "height": 12},
    },
    "1920x1080": {
        "res": (1920, 1080),
        "template_folder": "templates/1080",
        "minimap_region": (8, 55, 170, 75),
        "hp_bar_offset": {"x_offset": -100, "y_from_bottom": 68, "width": 200, "height": 16},
        "mp_bar_offset": {"x_offset": -100, "y_from_bottom": 50, "width": 200, "height": 16},
        "exp_bar_offset": {"x_offset": -200, "y_from_bottom": 16, "width": 400, "height": 14},
    },
}

DEFAULT_RESOLUTION = "1366x768"

# Current active offsets (set at runtime by template manager)
HP_BAR_OFFSET = RESOLUTION_PRESETS[DEFAULT_RESOLUTION]["hp_bar_offset"]
MP_BAR_OFFSET = RESOLUTION_PRESETS[DEFAULT_RESOLUTION]["mp_bar_offset"]
EXP_BAR_OFFSET = RESOLUTION_PRESETS[DEFAULT_RESOLUTION]["exp_bar_offset"]
