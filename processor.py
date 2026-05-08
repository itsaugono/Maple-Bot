import threading
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
import cv2
import config

try:
    import pytesseract
    if os.path.exists(config.TESSERACT_CMD):
        pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD
except ImportError:
    pytesseract = None


@dataclass
class GameState:
    player_pos: tuple[int, int] = (0, 0)
    target_pos: tuple[int, int] = (0, 0)
    pstate: str = "Unknown"
    hp_pct: float = 0.0
    mp_pct: float = 0.0
    exp_pct: float = 0.0
    portal_count: int = 0
    others_count: int = 0
    minimap_size: tuple[int, int] = (0, 0)


def _run_ocr_hpmp(region_data: bytes, width: int, height: int) -> float:
    if pytesseract is None:
        return 0.0
    try:
        arr = np.frombuffer(region_data, dtype=np.uint8).reshape(height, width, 3)
        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        text = pytesseract.image_to_string(
            thresh,
            lang=config.TESSERACT_LANG,
            config=config.HPMP_OCR_CONFIG,
        )
        text = text.strip().replace(" ", "")
        match = re.search(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)", text)
        if match:
            current = int(match.group(1).replace(",", ""))
            maximum = int(match.group(2).replace(",", ""))
            if maximum > 0:
                return round(current / maximum * 100, 2)
    except Exception:
        pass
    return 0.0


def _run_ocr_exp(region_data: bytes, width: int, height: int) -> float:
    if pytesseract is None:
        return 0.0
    try:
        arr = np.frombuffer(region_data, dtype=np.uint8).reshape(height, width, 3)
        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        text = pytesseract.image_to_string(
            thresh,
            lang=config.TESSERACT_LANG,
            config=config.EXP_OCR_CONFIG,
        )
        text = text.strip()
        match = re.search(r"\[(\d+[\.,]?\d*)\s*%\]", text)
        if match:
            return float(match.group(1).replace(",", "."))
    except Exception:
        pass
    return 0.0


class MapProcessor:
    def __init__(self, template_manager=None):
        self._ocr_frame_counter = 0
        self._cached_hp = 0.0
        self._cached_mp = 0.0
        self._cached_exp = 0.0
        self._template_manager = template_manager
        self.disable_ocr = False
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._ocr_pending = False
        self._ocr_lock = threading.Lock()

    def process_frame(self, frame: np.ndarray) -> GameState:
        state = GameState()
        minimap = self.extract_minimap(frame)
        state.minimap_size = (minimap.shape[1], minimap.shape[0])
        state.player_pos = self.find_player(minimap)
        portals = self.find_portals(minimap)
        state.portal_count = len(portals)
        state.pstate = self.detect_pstate(frame)
        state.hp_pct = self._cached_hp
        state.mp_pct = self._cached_mp
        state.exp_pct = self._cached_exp
        if self.disable_ocr:
            return state
        self._ocr_frame_counter += 1
        if self._ocr_frame_counter >= config.OCR_THROTTLE_FRAMES:
            self._ocr_frame_counter = 0
            self._dispatch_ocr(frame)
        return state

    def _dispatch_ocr(self, frame: np.ndarray):
        with self._ocr_lock:
            if self._ocr_pending:
                return
            self._ocr_pending = True

        # HP/MP regions
        if self._template_manager is not None:
            hp_region = self._template_manager.get_region("hp")
            mp_region = self._template_manager.get_region("mp")
            exp_region = self._template_manager.get_region("exp")
        else:
            hp_region = config.HP_BAR_REGION
            mp_region = config.MP_BAR_REGION
            exp_region = config.EXP_BAR_REGION
        if hp_region is None:
            hp_region = config.HP_BAR_REGION
        if mp_region is None:
            mp_region = config.MP_BAR_REGION
        if exp_region is None:
            exp_region = config.EXP_BAR_REGION

        def _grab_region(region, fn):
            """Extract region data and dispatch OCR to thread pool."""
            x, y, w, h = region
            if w == 0 or h == 0:
                return None
            roi = frame[y : y + h, x : x + w].copy()
            return roi.tobytes(), w, h, fn

        tasks = []
        hp_task = _grab_region(hp_region, _run_ocr_hpmp)
        if hp_task is not None:
            tasks.append(("hp", hp_task))
        mp_task = _grab_region(mp_region, _run_ocr_hpmp)
        if mp_task is not None:
            tasks.append(("mp", mp_task))
        exp_task = _grab_region(exp_region, _run_ocr_exp)
        if exp_task is not None:
            tasks.append(("exp", exp_task))

        if not tasks:
            with self._ocr_lock:
                self._ocr_pending = False
            return

        def _process_all():
            results = {}
            for name, (data, w, h, fn) in tasks:
                results[name] = fn(data, w, h)
            if "hp" in results:
                self._cached_hp = results["hp"]
            if "mp" in results:
                self._cached_mp = results["mp"]
            if "exp" in results:
                self._cached_exp = results["exp"]
            with self._ocr_lock:
                self._ocr_pending = False

        self._executor.submit(_process_all)

    def extract_minimap(self, frame: np.ndarray) -> np.ndarray:
        if self._template_manager is not None:
            region = self._template_manager.get_region("minimap")
            if region is None:
                region = self._template_manager.get_minimap_fallback_region()
        else:
            region = config.MINIMAP_REGION
        x, y, w, h = region
        if x + w > frame.shape[1] or y + h > frame.shape[0]:
            return np.zeros((71, 229, 3), dtype=np.uint8)
        return frame[y : y + h, x : x + w].copy()

    def find_player(self, minimap: np.ndarray) -> tuple[int, int]:
        if minimap.size == 0:
            return (0, 0)
        hsv = cv2.cvtColor(minimap, cv2.COLOR_BGR2HSV)
        lower = np.array(config.PLAYER_DOT_COLOR_LOW, dtype=np.uint8)
        upper = np.array(config.PLAYER_DOT_COLOR_HIGH, dtype=np.uint8)
        mask = cv2.inRange(hsv, lower, upper)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return (0, 0)
        largest = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(largest)
        return (x + w // 2, y + h // 2)

    def find_portals(self, minimap: np.ndarray) -> list[tuple[int, int]]:
        if minimap.size == 0:
            return []
        hsv = cv2.cvtColor(minimap, cv2.COLOR_BGR2HSV)
        lower = np.array(config.PORTAL_COLOR_LOW, dtype=np.uint8)
        upper = np.array(config.PORTAL_COLOR_HIGH, dtype=np.uint8)
        mask = cv2.inRange(hsv, lower, upper)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        portals = []
        for cnt in contours:
            if cv2.contourArea(cnt) > 20:
                x, y, w, h = cv2.boundingRect(cnt)
                portals.append((x + w // 2, y + h // 2))
        return portals

    def detect_pstate(self, frame: np.ndarray) -> str:
        return "Grounded"
