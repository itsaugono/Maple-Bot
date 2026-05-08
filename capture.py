import threading
import time
import mss
import numpy as np
import win32gui
import win32con


class CaptureThread(threading.Thread):
    def __init__(self, target_fps=60):
        super().__init__(daemon=True)
        self.target_fps = target_fps
        self.frame_interval = 1.0 / target_fps
        self._hwnd = None
        self._window_rect = None
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._selected = False
        self.fps_tracker = {"frames": 0, "last_time": time.time(), "current_fps": 0.0}

    def select_window(self, title=None) -> bool:
        try:
            if title is not None:
                self._hwnd = win32gui.FindWindow(None, title)
                if not self._hwnd:
                    return False
            else:
                # Case-insensitive search for specific titles
                target_titles = ["maplestory", "rien", "haiku"]
                def callback(hwnd, extra):
                    window_title = win32gui.GetWindowText(hwnd).lower()
                    if window_title in target_titles:
                        extra.append(hwnd)
                        return False  # stop enumeration
                    return True
                hwnds = []
                win32gui.EnumWindows(callback, hwnds)
                if not hwnds:
                    return False
                self._hwnd = hwnds[0]
            left, top, right, bottom = win32gui.GetClientRect(self._hwnd)
            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                return False
            # Convert client-relative (0,0) to absolute screen coordinates
            screen_left, screen_top = win32gui.ClientToScreen(self._hwnd, (left, top))
            self._window_rect = {"left": screen_left, "top": screen_top, "width": width, "height": height}
            self._selected = True
            return True
        except Exception:
            return False

    def get_frame(self):
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def is_selected(self) -> bool:
        return self._selected

    def get_window_rect(self):
        return self._window_rect

    def get_fps(self) -> float:
        return self.fps_tracker["current_fps"]

    def run(self):
        self._running = True
        with mss.mss() as sct:
            while self._running:
                loop_start = time.time()
                if not self._selected or self._window_rect is None:
                    time.sleep(0.1)
                    continue
                try:
                    monitor = {
                        "left": self._window_rect["left"],
                        "top": self._window_rect["top"],
                        "width": self._window_rect["width"],
                        "height": self._window_rect["height"],
                    }
                    screenshot = sct.grab(monitor)
                    frame = np.array(screenshot)
                    frame = frame[:, :, :3]
                    with self._lock:
                        self._frame = frame
                    self._update_fps()
                except Exception:
                    pass
                elapsed = time.time() - loop_start
                sleep_time = self.frame_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

    def stop(self):
        self._running = False

    def _update_fps(self):
        now = time.time()
        self.fps_tracker["frames"] += 1
        if now - self.fps_tracker["last_time"] >= 1.0:
            self.fps_tracker["current_fps"] = self.fps_tracker["frames"] / (
                now - self.fps_tracker["last_time"]
            )
            self.fps_tracker["frames"] = 0
            self.fps_tracker["last_time"] = now
