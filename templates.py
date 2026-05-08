import json
import os
from typing import Optional

import cv2
import numpy as np

import config


CORNER_NAMES = ["minimap_corner_tl", "minimap_corner_tr", "minimap_corner_bl", "minimap_corner_br"]


class TemplateManager:
    def __init__(self):
        self._templates = {}
        self._detected_regions = {}
        self._detected = False
        self._minimap_detected = False
        self._current_resolution = config.DEFAULT_RESOLUTION
        self._preset = config.RESOLUTION_PRESETS[self._current_resolution]
        self._template_folder = self._preset["template_folder"]
        # Per-resolution bar offsets: {"1366x768": {"hp": {...}, ...}, "1920x1080": {...}}
        self._all_bar_offsets = {}
        for res_name, res_preset in config.RESOLUTION_PRESETS.items():
            self._all_bar_offsets[res_name] = {
                "hp": dict(res_preset["hp_bar_offset"]),
                "mp": dict(res_preset["mp_bar_offset"]),
                "exp": dict(res_preset["exp_bar_offset"]),
            }
        self._bar_offsets = self._all_bar_offsets[self._current_resolution]
        os.makedirs("templates/768", exist_ok=True)
        os.makedirs("templates/1080", exist_ok=True)
        os.makedirs("templates/custom", exist_ok=True)

    def get_current_resolution(self) -> str:
        return self._current_resolution

    def get_available_resolutions(self) -> list:
        return list(config.RESOLUTION_PRESETS.keys())

    def set_resolution(self, resolution: str):
        """Switch to a different resolution preset and reload templates."""
        if resolution not in config.RESOLUTION_PRESETS:
            return
        self._current_resolution = resolution
        self._preset = config.RESOLUTION_PRESETS[resolution]
        self._template_folder = self._preset["template_folder"]
        self._bar_offsets = self._all_bar_offsets[self._current_resolution]
        self._templates.clear()
        self._detected_regions.clear()
        self._detected = False
        self._minimap_detected = False
        self._load_templates()
        self.save_config()

    def get_minimap_fallback_region(self) -> tuple:
        return self._preset["minimap_region"]

    def load_config(self):
        config_path = config.TEMPLATES_CONFIG
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    data = json.load(f)
                # Restore per-resolution bar offsets
                if "bar_offsets_per_res" in data:
                    for res_name, offsets in data["bar_offsets_per_res"].items():
                        if res_name in self._all_bar_offsets:
                            for bar in ("hp", "mp", "exp"):
                                if bar in offsets:
                                    self._all_bar_offsets[res_name][bar].update(offsets[bar])
                if "resolution" in data:
                    res = data["resolution"]
                    if res in config.RESOLUTION_PRESETS:
                        self._current_resolution = res
                        self._preset = config.RESOLUTION_PRESETS[res]
                        self._template_folder = self._preset["template_folder"]
                        self._bar_offsets = self._all_bar_offsets[self._current_resolution]
            except (json.JSONDecodeError, KeyError):
                pass
        self._load_templates()

    def save_config(self):
        config_path = config.TEMPLATES_CONFIG
        data = {
            "resolution": self._current_resolution,
            "bar_offsets_per_res": self._all_bar_offsets,
        }
        with open(config_path, "w") as f:
            json.dump(data, f, indent=2)

    def _load_templates(self):
        """Load corner templates from the resolution-specific folder."""
        self._templates.clear()
        for name in CORNER_NAMES:
            path = os.path.join(self._template_folder, f"{name}.png")
            if os.path.exists(path):
                img = cv2.imread(path)
                if img is not None:
                    self._templates[name] = img

    def load_custom_template(self, name: str, path: str) -> bool:
        img = cv2.imread(path)
        if img is not None:
            self._templates[name] = img
            # Copy to the resolution folder for persistence
            dest = os.path.join(self._template_folder, f"{name}.png")
            cv2.imwrite(dest, img)
            self._detected = False
            self._minimap_detected = False
            return True
        return False

    def get_template_folder(self) -> str:
        return self._template_folder

    def get_template_status(self) -> dict:
        return {name: name in self._templates for name in CORNER_NAMES}

    def get_bar_offsets(self) -> dict:
        return self._bar_offsets

    def set_bar_offset(self, bar: str, key: str, value: int):
        if bar in self._bar_offsets:
            self._bar_offsets[bar][key] = value

    def detect_regions(self, frame: np.ndarray) -> bool:
        if frame is None:
            return False
        self._detected = True
        minimap_region = self._find_minimap(frame)
        self._detected_regions["minimap"] = minimap_region
        self._minimap_detected = minimap_region is not None
        self._compute_bar_regions(frame.shape[1], frame.shape[0])
        return self._minimap_detected

    def _find_minimap(self, frame: np.ndarray) -> Optional[tuple]:
        # Try 4-corner detection first
        region = self._find_minimap_4corners(frame)
        if region is not None:
            return region

        # Fall back to 2-corner (TL + BR) detection
        region = self._find_minimap_2corners(frame)
        if region is not None:
            return region

        return None

    def _match_template(self, frame: np.ndarray, name: str) -> Optional[tuple]:
        """Match a named template against the frame.
        Returns (x, y, confidence) or None if template not loaded."""
        template = self._templates.get(name)
        if template is None:
            return None

        th, tw = template.shape[:2]
        if frame.shape[0] < th or frame.shape[1] < tw:
            return None

        result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val < config.MATCH_THRESHOLD:
            return None

        return (max_loc[0], max_loc[1], max_val)

    def _find_minimap_4corners(self, frame: np.ndarray) -> Optional[tuple]:
        """Use all 4 corners for maximum accuracy."""
        tl = self._templates.get("minimap_corner_tl")
        tr = self._templates.get("minimap_corner_tr")
        bl = self._templates.get("minimap_corner_bl")
        br = self._templates.get("minimap_corner_br")

        if tl is None or tr is None or bl is None or br is None:
            return None

        match_tl = self._match_template(frame, "minimap_corner_tl")
        match_tr = self._match_template(frame, "minimap_corner_tr")
        match_bl = self._match_template(frame, "minimap_corner_bl")
        match_br = self._match_template(frame, "minimap_corner_br")

        if any(m is None for m in [match_tl, match_tr, match_bl, match_br]):
            return None

        tl_h, tl_w = tl.shape[:2]
        tr_h, _ = tr.shape[:2]
        _, bl_w = bl.shape[:2]

        # Content region bounded by the inner edges of all 4 corners
        x_left = max(match_tl[0] + tl_w, match_bl[0] + bl_w)
        y_top = max(match_tl[1] + tl_h, match_tr[1] + tr_h)
        x_right = min(match_tr[0], match_br[0])
        y_bottom = min(match_bl[1], match_br[1])

        width = x_right - x_left
        height = y_bottom - y_top

        if width < 20 or height < 20:
            return None

        return (x_left, y_top, width, height)

    def _find_minimap_2corners(self, frame: np.ndarray) -> Optional[tuple]:
        """Fallback: use only TL + BR corners."""
        tl = self._templates.get("minimap_corner_tl")
        br = self._templates.get("minimap_corner_br")

        if tl is None or br is None:
            return None

        match_tl = self._match_template(frame, "minimap_corner_tl")
        match_br = self._match_template(frame, "minimap_corner_br")

        if match_tl is None or match_br is None:
            return None

        tl_h, tl_w = tl.shape[:2]

        x1 = match_tl[0] + tl_w
        y1 = match_tl[1] + tl_h
        x2 = match_br[0]
        y2 = match_br[1]

        width = x2 - x1
        height = y2 - y1

        if width < 20 or height < 20:
            return None

        return (x1, y1, width, height)

    def _compute_bar_regions(self, frame_w: int, frame_h: int):
        center_x = frame_w // 2
        for bar in ("hp", "mp", "exp"):
            offsets = self._bar_offsets[bar]
            x = center_x + offsets["x_offset"]
            y = frame_h - offsets["y_from_bottom"] - offsets["height"]
            w = offsets["width"]
            h = offsets["height"]
            self._detected_regions[bar] = (x, y, w, h)

    def get_region(self, name: str) -> Optional[tuple]:
        return self._detected_regions.get(name)

    def is_detected(self) -> bool:
        return self._detected

    def is_minimap_detected(self) -> bool:
        return self._minimap_detected

    def is_template_loaded(self, name: str) -> bool:
        return name in self._templates
