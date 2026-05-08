import time

import dearpygui.dearpygui as dpg
import numpy as np
import cv2
import config
from capture import CaptureThread
from processor import MapProcessor, GameState
from templates import CORNER_NAMES


# Threshold for detecting a "black screen" (mean pixel value)
BLACK_SCREEN_THRESHOLD = 15
# How many frames to wait after black screen clears before re-detecting
REDETECT_DELAY_FRAMES = 30
# How many re-detect attempts after recovery
REDETECT_ATTEMPTS = 5


class MapleStoryUI:
    def __init__(self, template_manager=None):
        self.capture_thread = CaptureThread(target_fps=60)
        self.template_manager = template_manager
        self.processor = MapProcessor(template_manager)
        self.game_state = GameState()
        self._live_texture = None
        self._minimap_texture = None
        self._dirty_live = False
        self._dirty_minimap = False
        self._latest_frame = None
        self._latest_minimap = None
        self._auto_detect_triggered = False
        self._show_overlay = False
        # Black screen / auto-redetect state
        self._was_black = False
        self._redetect_countdown = 0
        self._redetect_attempts_left = 0
        # Frame skip for processing (process every N render frames)
        self._frame_counter = 0
        self._process_every_n = 2

    def setup(self):
        dpg.create_context()
        dpg.create_viewport(title="MapleStory-Py", width=950, height=700)
        self._build_ui()
        self._update_settings_status()
        dpg.setup_dearpygui()

    def _build_ui(self):
        with dpg.texture_registry():
            self._live_texture = dpg.add_dynamic_texture(
                683, 384, [0.0] * (683 * 384 * 4)
            )
            self._minimap_texture = dpg.add_dynamic_texture(
                458, 142, [0.0] * (458 * 142 * 4)
            )

        # File dialogs for each corner template
        for corner in CORNER_NAMES:
            label = corner.replace("minimap_corner_", "").upper()
            with dpg.file_dialog(
                label=f"Select {label} Corner Template",
                tag=f"file_dialog_{corner}",
                width=600,
                height=400,
                show=False,
                callback=self._on_corner_file_selected,
                user_data=corner,
            ):
                dpg.add_file_extension(".png")
                dpg.add_file_extension(".jpg")
                dpg.add_file_extension(".bmp")
                dpg.add_file_extension(".*")

        with dpg.window(tag="main_window", no_title_bar=True, no_move=True):
            dpg.set_primary_window("main_window", True)

            with dpg.collapsing_header(label="Capture", default_open=True):
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Select Window",
                        callback=self._on_select_window,
                        tag="btn_select",
                    )
                    dpg.add_combo(
                        items=self.template_manager.get_available_resolutions(),
                        default_value=self.template_manager.get_current_resolution(),
                        callback=self._on_resolution_changed,
                        tag="combo_resolution",
                        width=120,
                    )
                    dpg.add_text(
                        "[ ] NOT CAPTURING",
                        tag="status_fps",
                        color=(150, 150, 150),
                    )

                dpg.add_text(
                    "Window: --  Minimap: --\n"
                    "Player: (0,0)  Target: (0,0)  PState: --\n"
                    "HP: 0%  MP: 0%  Portals: 0  Others: 0  Fam: --\n"
                    "EXP: 0.00%  EXP/h: --  Next Level: --",
                    tag="status_info",
                    color=(200, 200, 200),
                )

                dpg.add_checkbox(
                    label="Disable OCR (tesseract)",
                    default_value=False,
                    callback=self._on_ocr_toggle,
                    tag="chk_disable_ocr",
                )

            with dpg.tab_bar():
                with dpg.tab(label="Minimap"):
                    dpg.add_image(
                        self._minimap_texture,
                        width=458,
                        height=142,
                        tag="img_minimap",
                    )
                    dpg.add_text(
                        "Minimap: not yet detected",
                        tag="minimap_detect_status",
                        color=(150, 150, 150),
                    )

                with dpg.tab(label="Live Capture"):
                    dpg.add_checkbox(
                        label="Show Detection Overlay",
                        default_value=False,
                        callback=self._on_overlay_toggle,
                        tag="chk_overlay",
                    )
                    dpg.add_image(
                        self._live_texture,
                        width=683,
                        height=384,
                        tag="img_live",
                    )

                self._build_settings_tab()

    def _build_settings_tab(self):
        with dpg.tab(label="Settings"):
            dpg.add_text(
                "Configure template images and bar offsets.",
                color=(180, 180, 180),
                wrap=700,
            )

            # --- Minimap Templates ---
            dpg.add_separator()
            dpg.add_text("Minimap Corner Templates", color=(255, 255, 255))
            dpg.add_text(
                "Provide 4 corner crops of the inner white border lines for best detection.\n"
                "At minimum, TL + BR are required. All 4 gives perfect coverage.",
                color=(140, 140, 140),
                wrap=700,
            )

            corner_labels = {
                "minimap_corner_tl": "Top-left",
                "minimap_corner_tr": "Top-right",
                "minimap_corner_bl": "Bottom-left",
                "minimap_corner_br": "Bottom-right",
            }
            for corner in CORNER_NAMES:
                label = corner_labels[corner]
                with dpg.group(horizontal=True):
                    dpg.add_text(f"{label}:", color=(180, 180, 180))
                    dpg.add_text(
                        "NOT FOUND",
                        tag=f"settings_{corner}_status",
                        color=(255, 100, 100),
                    )
                    dpg.add_button(
                        label="Browse...",
                        callback=lambda s, a, u=corner: dpg.show_item(f"file_dialog_{u}"),
                        tag=f"btn_browse_{corner}",
                    )

            # --- Bar Offsets ---
            dpg.add_separator()
            dpg.add_text("Bar Offsets (from bottom-center of frame)", color=(255, 255, 255))
            dpg.add_text(
                "Adjust these values and use the overlay on Live Capture to verify alignment.",
                color=(140, 140, 140),
                wrap=700,
            )

            for bar, label, color in [
                ("hp", "HP", (255, 100, 100)),
                ("mp", "MP", (100, 150, 255)),
                ("exp", "EXP", (100, 255, 255)),
            ]:
                with dpg.group(horizontal=True):
                    dpg.add_text(f"{label}:", color=color)
                    dpg.add_text(" x_off", color=(180, 180, 180))
                    dpg.add_input_int(
                        default_value=self.template_manager.get_bar_offsets()[bar]["x_offset"],
                        width=70,
                        tag=f"settings_{bar}_x_offset",
                        callback=self._on_bar_offset_changed,
                        user_data={"bar": bar, "key": "x_offset"},
                    )
                    dpg.add_text(" y_bot", color=(180, 180, 180))
                    dpg.add_input_int(
                        default_value=self.template_manager.get_bar_offsets()[bar]["y_from_bottom"],
                        width=70,
                        tag=f"settings_{bar}_y_from_bottom",
                        callback=self._on_bar_offset_changed,
                        user_data={"bar": bar, "key": "y_from_bottom"},
                    )
                    dpg.add_text(" w", color=(180, 180, 180))
                    dpg.add_input_int(
                        default_value=self.template_manager.get_bar_offsets()[bar]["width"],
                        width=70,
                        tag=f"settings_{bar}_w",
                        callback=self._on_bar_offset_changed,
                        user_data={"bar": bar, "key": "width"},
                    )
                    dpg.add_text(" h", color=(180, 180, 180))
                    dpg.add_input_int(
                        default_value=self.template_manager.get_bar_offsets()[bar]["height"],
                        width=60,
                        tag=f"settings_{bar}_h",
                        callback=self._on_bar_offset_changed,
                        user_data={"bar": bar, "key": "height"},
                    )

            # --- Detection ---
            dpg.add_separator()
            dpg.add_text("Detection", color=(255, 255, 255))

            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Re-detect Regions",
                    callback=self._on_detect_regions,
                    tag="btn_detect",
                )
                dpg.add_text(
                    "Not yet detected",
                    tag="settings_detect_status",
                    color=(150, 150, 150),
                )

            dpg.add_text(
                "Minimap: not detected\n"
                "HP: not computed\n"
                "MP: not computed\n"
                "EXP: not computed",
                tag="settings_region_info",
                color=(180, 180, 180),
            )

            dpg.add_separator()
            dpg.add_text("Auto-Detection", color=(255, 255, 255))
            dpg.add_text(
                "Regions are automatically re-detected when a map change is detected\n"
                "(black screen transition).",
                color=(140, 140, 140),
                wrap=700,
            )

    # --- File dialog callbacks ---

    def _on_corner_file_selected(self, sender, app_data, user_data):
        corner_name = user_data
        file_path = app_data.get("file_path_name") if app_data else None
        if file_path and self.template_manager:
            if self.template_manager.load_custom_template(corner_name, file_path):
                self.template_manager.save_config()
                self._update_settings_status()
                if self._latest_frame is not None:
                    self.template_manager.detect_regions(self._latest_frame)
                    self._update_settings_status()

    def _on_bar_offset_changed(self, sender, app_data, user_data):
        if not self.template_manager:
            return
        bar = user_data["bar"]
        key = user_data["key"]
        value = app_data
        self.template_manager.set_bar_offset(bar, key, value)
        self.template_manager.save_config()
        if self._latest_frame is not None:
            self.template_manager.detect_regions(self._latest_frame)
            self._update_settings_status()

    def _on_detect_regions(self):
        if self._latest_frame is not None and self.template_manager:
            self.template_manager.detect_regions(self._latest_frame)
            self._update_settings_status()

    def _on_overlay_toggle(self, sender, app_data):
        self._show_overlay = app_data

    def _on_ocr_toggle(self, sender, app_data):
        self.processor.disable_ocr = app_data

    def _on_resolution_changed(self, sender, app_data):
        if not self.template_manager:
            return
        self.template_manager.set_resolution(app_data)
        # Update the bar offset input fields to reflect new preset values
        for bar in ("hp", "mp", "exp"):
            offsets = self.template_manager.get_bar_offsets()[bar]
            dpg.set_value(f"settings_{bar}_x_offset", offsets["x_offset"])
            dpg.set_value(f"settings_{bar}_y_from_bottom", offsets["y_from_bottom"])
            dpg.set_value(f"settings_{bar}_w", offsets["width"])
            dpg.set_value(f"settings_{bar}_h", offsets["height"])
        self._update_settings_status()
        # Re-detect with new templates if we have a frame
        if self._latest_frame is not None:
            self.template_manager.detect_regions(self._latest_frame)
            self._update_settings_status()

    # --- Settings status update ---

    def _update_settings_status(self):
        if self.template_manager is None:
            return

        status = self.template_manager.get_template_status()
        folder = self.template_manager.get_template_folder()

        # Corner template status
        for corner in CORNER_NAMES:
            tag = f"settings_{corner}_status"
            if status.get(corner, False):
                dpg.set_value(tag, f"{folder}/{corner}.png")
                dpg.configure_item(tag, color=(100, 255, 100))
            else:
                dpg.set_value(tag, f"NOT FOUND in {folder}/")
                dpg.configure_item(tag, color=(255, 100, 100))

        # Detection results
        if self.template_manager.is_detected():
            mm = self.template_manager.get_region("minimap")
            hp = self.template_manager.get_region("hp")
            mp = self.template_manager.get_region("mp")
            exp = self.template_manager.get_region("exp")

            if self.template_manager.is_minimap_detected():
                dpg.set_value("settings_detect_status", "Regions detected")
                dpg.configure_item("settings_detect_status", color=(100, 255, 100))
                dpg.set_value(
                    "minimap_detect_status",
                    f"Detected at ({mm[0]}, {mm[1]}, {mm[2]}, {mm[3]})",
                )
                dpg.configure_item("minimap_detect_status", color=(100, 255, 100))
            else:
                fallback = self.template_manager.get_minimap_fallback_region()
                dpg.set_value("settings_detect_status", "Minimap NOT detected (using fallback)")
                dpg.configure_item("settings_detect_status", color=(255, 200, 50))
                dpg.set_value(
                    "minimap_detect_status",
                    f"Not detected - using fallback region {fallback}",
                )
                dpg.configure_item("minimap_detect_status", color=(255, 200, 50))

            def fmt(r):
                return f"({r[0]}, {r[1]}, {r[2]}, {r[3]})" if r else "not found"

            fallback = self.template_manager.get_minimap_fallback_region()
            mm_str = fmt(mm) if mm else f"FALLBACK {fallback}"
            dpg.set_value(
                "settings_region_info",
                f"Minimap: {mm_str}\n"
                f"HP: {fmt(hp)}\n"
                f"MP: {fmt(mp)}\n"
                f"EXP: {fmt(exp)}",
            )
        else:
            dpg.set_value("settings_detect_status", "Not yet detected")
            dpg.configure_item("settings_detect_status", color=(150, 150, 150))

    # --- Black screen detection ---

    def _is_black_screen(self, frame: np.ndarray) -> bool:
        """Check if the frame is mostly black (map transition)."""
        mean_val = np.mean(frame)
        return mean_val < BLACK_SCREEN_THRESHOLD

    # --- Main loop ---

    def run(self):
        dpg.show_viewport()
        dpg.set_primary_window("main_window", True)
        while dpg.is_dearpygui_running():
            self._render_callback()
            dpg.render_dearpygui_frame()
        self.capture_thread.stop()
        dpg.destroy_context()

    def _on_select_window(self):
        if self.capture_thread.select_window():
            dpg.configure_item("btn_select", label="Window Selected")
            dpg.set_value("status_fps", "[+] CAPTURING (0.0 FPS)")
            dpg.configure_item("status_fps", color=(100, 255, 100))
            if not self.capture_thread.is_alive():
                self.capture_thread.start()
            self._auto_detect_triggered = True
        else:
            dpg.set_value("status_fps", "[!] Window not found")
            dpg.configure_item("status_fps", color=(255, 100, 100))

    def _render_callback(self):
        frame = self.capture_thread.get_frame()
        if frame is not None:
            self._latest_frame = frame

            # Auto-detect on first frame after window selection
            if self._auto_detect_triggered and self.template_manager:
                self._auto_detect_triggered = False
                self.template_manager.detect_regions(frame)
                self._update_settings_status()

            # Black screen detection for map transitions
            is_black = self._is_black_screen(frame)
            if is_black:
                self._was_black = True
            elif self._was_black:
                # Screen just recovered from black — schedule re-detection
                self._was_black = False
                self._redetect_countdown = REDETECT_DELAY_FRAMES
                self._redetect_attempts_left = REDETECT_ATTEMPTS

            # Re-detect countdown after black screen recovery
            if self._redetect_countdown > 0:
                self._redetect_countdown -= 1
            elif self._redetect_attempts_left > 0:
                self._redetect_attempts_left -= 1
                if self.template_manager:
                    success = self.template_manager.detect_regions(frame)
                    self._update_settings_status()
                    if success:
                        self._redetect_attempts_left = 0
                    else:
                        # Wait a few more frames before next attempt
                        self._redetect_countdown = 10

            # Process frame (skip some frames to reduce load)
            self._frame_counter += 1
            if not is_black and self._frame_counter >= self._process_every_n:
                self._frame_counter = 0
                minimap = self.processor.extract_minimap(frame)
                self._latest_minimap = minimap
                self.game_state = self.processor.process_frame(frame)
                self._dirty_minimap = True

            self._dirty_live = True

        if self._dirty_live and self._latest_frame is not None:
            self._update_live_texture(self._latest_frame)
            self._dirty_live = False

        if self._dirty_minimap and self._latest_minimap is not None:
            self._update_minimap_texture(self._latest_minimap)
            self._dirty_minimap = False

        self._update_status_text()

    def _update_live_texture(self, frame: np.ndarray):
        display_frame = frame
        if self._show_overlay and self.template_manager:
            display_frame = frame.copy()
            self._draw_overlay(display_frame)
        scaled = cv2.resize(display_frame, (683, 384), interpolation=cv2.INTER_AREA)
        rgba = cv2.cvtColor(scaled, cv2.COLOR_BGR2RGBA)
        rgba_float = (rgba.astype(np.float32) / 255.0).ravel()
        dpg.set_value(self._live_texture, rgba_float)

    def _draw_overlay(self, frame: np.ndarray):
        regions = {
            "minimap": (0, 255, 0),      # green
            "hp": (0, 0, 255),           # red (BGR)
            "mp": (255, 100, 0),         # blue (BGR)
            "exp": (0, 255, 255),        # yellow (BGR)
        }
        for name, color in regions.items():
            region = self.template_manager.get_region(name)
            if region is not None:
                x, y, w, h = region
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                cv2.putText(
                    frame,
                    name.upper(),
                    (x + 2, y - 4),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4,
                    color,
                    1,
                )
        # Also draw fallback minimap region if minimap not detected
        if not self.template_manager.is_minimap_detected():
            x, y, w, h = self.template_manager.get_minimap_fallback_region()
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 200, 200), 1)
            cv2.putText(
                frame,
                "FALLBACK",
                (x + 2, y - 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                (0, 200, 200),
                1,
            )

    def _update_minimap_texture(self, minimap: np.ndarray):
        if minimap.shape[0] == 0 or minimap.shape[1] == 0:
            return
        scaled = cv2.resize(minimap, (458, 142), interpolation=cv2.INTER_AREA)
        rgba = cv2.cvtColor(scaled, cv2.COLOR_BGR2RGBA)
        rgba_float = (rgba.astype(np.float32) / 255.0).ravel()
        dpg.set_value(self._minimap_texture, rgba_float)

    def _update_status_text(self):
        fps = self.capture_thread.get_fps()
        rect = self.capture_thread.get_window_rect()
        if rect:
            win_str = f"{rect['width']}x{rect['height']}"
        else:
            win_str = "--"
        mm = self.game_state.minimap_size
        mm_str = f"{mm[0]}x{mm[1]}" if mm[0] > 0 else "--"
        pp = self.game_state.player_pos
        tp = self.game_state.target_pos
        dpg.set_value("status_fps", f"[+] CAPTURING ({fps:.1f} FPS)")
        dpg.configure_item("status_fps", color=(100, 255, 100))
        dpg.set_value(
            "status_info",
            f"Window: {win_str}  Minimap: {mm_str}\n"
            f"Player: {pp}  Target: {tp}  PState: {self.game_state.pstate}\n"
            f"HP: {self.game_state.hp_pct:.0f}%  MP: {self.game_state.mp_pct:.0f}%  "
            f"Portals: {self.game_state.portal_count}  Others: {self.game_state.others_count}  Fam: --\n"
            f"EXP: {self.game_state.exp_pct:.2f}%  EXP/h: --  Next Level: --",
        )
