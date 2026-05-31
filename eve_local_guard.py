# -*- coding: utf-8 -*-
"""
EVE Local Guard

A small Windows companion tool that watches a user-selected part of the
screen and alerts when EVE Online's local member list contains hostile or
neutral rows. Blue, purple, and green rows are treated as friendly. Red,
orange, and rows without a friendly marker are treated as threats.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
import struct
import sys
import time
import traceback
import wave
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import messagebox, ttk


try:
    from PIL import Image, ImageDraw, ImageGrab

    PIL_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - depends on user environment
    Image = None
    ImageDraw = None
    ImageGrab = None
    PIL_IMPORT_ERROR = exc

try:
    import mss

    MSS_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - depends on user environment
    mss = None
    MSS_IMPORT_ERROR = exc


APP_NAME = "EVE Local Guard"
CONFIG_DIR_NAME = "EVELocalGuard"


DEFAULT_CONFIG = {
    "region": {
        "x": 0,
        "y": 0,
        "width": 360,
        "height": 460,
    },
    "scan": {
        "detector_version": 2,
        "interval_ms": 700,
        "marker_x": 0,
        "marker_width": 0,
        "min_pixels_per_row": 6,
        "min_row_content_pixels": 28,
        "row_merge_gap": 3,
        "min_cluster_height": 3,
        "max_cluster_height": 80,
        "required_frames": 2,
        "clear_frames": 3,
        "cooldown_seconds": 8,
        "alert_red": True,
        "alert_orange": True,
        "alert_white": True,
        "sound": True,
        "sound_effect": "alarm",
        "popup": True,
        "persistent_alert": False,
        "topmost": True,
    },
}


def set_dpi_awareness() -> None:
    """Keep Windows display scaling from shifting screenshot coordinates."""
    if sys.platform != "win32":
        return

    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def app_data_dir() -> str:
    if sys.platform == "win32":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        root = os.path.expanduser("~")
    path = os.path.join(root, CONFIG_DIR_NAME)
    try:
        os.makedirs(path, exist_ok=True)
        return path
    except OSError:
        fallback = os.path.join(os.path.abspath(os.getcwd()), CONFIG_DIR_NAME)
        os.makedirs(fallback, exist_ok=True)
        return fallback


def config_path() -> str:
    return os.path.join(app_data_dir(), "config.json")


def deep_merge(base: Dict, override: Dict) -> Dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> Dict:
    path = config_path()
    if not os.path.exists(path):
        return deep_merge(DEFAULT_CONFIG, {})

    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        scan = data.get("scan")
        if isinstance(scan, dict) and "min_row_content_pixels" not in scan:
            scan["marker_width"] = 0
            scan["max_cluster_height"] = DEFAULT_CONFIG["scan"]["max_cluster_height"]
        if isinstance(scan, dict) and int(scan.get("detector_version", 1)) < DEFAULT_CONFIG["scan"]["detector_version"]:
            scan["detector_version"] = DEFAULT_CONFIG["scan"]["detector_version"]
            scan["marker_width"] = 0
            scan["min_pixels_per_row"] = DEFAULT_CONFIG["scan"]["min_pixels_per_row"]
            scan["min_row_content_pixels"] = DEFAULT_CONFIG["scan"]["min_row_content_pixels"]
        return deep_merge(DEFAULT_CONFIG, data)
    except Exception:
        return deep_merge(DEFAULT_CONFIG, {})


def save_config(data: Dict) -> None:
    with open(config_path(), "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def crash_log_path() -> str:
    return os.path.join(app_data_dir(), "crash.log")


def alert_sound_path() -> str:
    return os.path.join(app_data_dir(), "alert.wav")


def ensure_alert_sound() -> str:
    path = alert_sound_path()
    if os.path.exists(path):
        return path

    sample_rate = 44100
    volume = 0.55
    pattern = [
        (880, 0.16),
        (0, 0.05),
        (1320, 0.16),
        (0, 0.05),
        (660, 0.28),
    ]
    samples = bytearray()

    for freq, duration in pattern:
        count = int(sample_rate * duration)
        for index in range(count):
            if freq <= 0:
                value = 0
            else:
                fade = min(1.0, index / 500, (count - index) / 500)
                value = int(32767 * volume * fade * math.sin(2 * math.pi * freq * index / sample_rate))
            samples.extend(struct.pack("<h", value))

    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(samples))

    return path


def write_crash_log(exc: BaseException) -> str:
    path = crash_log_path()
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n" + "=" * 72 + "\n")
        handle.write(_dt.datetime.now().isoformat(timespec="seconds") + "\n")
        handle.write(f"{type(exc).__name__}: {exc}\n")
        handle.write(traceback.format_exc())
        handle.write("\n")
    return path


def clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def parse_int(value: str, default: int, low: Optional[int] = None, high: Optional[int] = None) -> int:
    try:
        parsed = int(float(str(value).strip()))
    except Exception:
        parsed = default
    if low is not None:
        parsed = max(low, parsed)
    if high is not None:
        parsed = min(high, parsed)
    return parsed


@dataclass
class Region:
    x: int
    y: int
    width: int
    height: int

    def normalized(self) -> "Region":
        return Region(
            x=int(self.x),
            y=int(self.y),
            width=max(1, int(self.width)),
            height=max(1, int(self.height)),
        )


@dataclass
class DetectorOptions:
    marker_x: int
    marker_width: int
    min_pixels_per_row: int
    min_row_content_pixels: int
    row_merge_gap: int
    min_cluster_height: int
    max_cluster_height: int
    alert_red: bool
    alert_orange: bool
    alert_white: bool


@dataclass
class DetectedRow:
    top: int
    bottom: int
    content_peak: int
    friend_pixels: int
    hostile_pixels: int
    status: str


@dataclass
class ThreatResult:
    count: int
    clusters: List[Tuple[int, int, int]]
    pixel_total: int
    marker_box: Tuple[int, int, int, int]
    marker_boxes: List[Tuple[int, int, int, int]]
    rows: List[DetectedRow]
    safe_count: int
    explicit_count: int
    neutral_count: int


class ScreenGrabber:
    def __init__(self) -> None:
        self._sct = None
        if mss is not None:
            try:
                self._sct = mss.mss()
            except Exception:
                self._sct = None

    def close(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
        self._sct = None

    def grab(self, region: Region):
        if PIL_IMPORT_ERROR is not None:
            raise RuntimeError(f"缺少 Pillow 依赖：{PIL_IMPORT_ERROR}")

        region = region.normalized()
        if self._sct is not None:
            raw = self._sct.grab(
                {
                    "left": region.x,
                    "top": region.y,
                    "width": region.width,
                    "height": region.height,
                }
            )
            return Image.frombytes("RGB", raw.size, raw.rgb)

        image = ImageGrab.grab(
            bbox=(region.x, region.y, region.x + region.width, region.y + region.height),
            all_screens=True,
        )
        return image.convert("RGB")


class ThreatDetector:
    def __init__(self, options: DetectorOptions) -> None:
        self.options = options

    def analyze(self, image) -> ThreatResult:
        if image.mode != "RGB":
            image = image.convert("RGB")

        width, height = image.size
        marker_ranges = self._marker_ranges(width)
        pixels = image.load()

        content_counts: List[int] = []
        for y in range(height):
            content_count = 0
            for x in range(width):
                r, g, b = pixels[x, y]
                if self._is_row_content_pixel(r, g, b):
                    content_count += 1
            content_counts.append(content_count)

        rows: List[DetectedRow] = []
        clusters: List[Tuple[int, int, int]] = []
        safe_count = 0
        explicit_count = 0
        neutral_count = 0
        pixel_total = 0

        for top, bottom, content_peak in self._cluster_rows(content_counts):
            friend_pixels, hostile_pixels = self._count_marker_pixels(pixels, marker_ranges, top, bottom)
            status = self._classify_row(friend_pixels, hostile_pixels)
            row = DetectedRow(
                top=top,
                bottom=bottom,
                content_peak=content_peak,
                friend_pixels=friend_pixels,
                hostile_pixels=hostile_pixels,
                status=status,
            )
            rows.append(row)

            if status == "safe":
                safe_count += 1
                continue

            clusters.append((top, bottom, max(content_peak, hostile_pixels)))
            pixel_total += hostile_pixels
            if status == "hostile":
                explicit_count += 1
            elif status == "neutral":
                neutral_count += 1

        return ThreatResult(
            count=len(clusters),
            clusters=clusters,
            pixel_total=pixel_total,
            marker_box=(marker_ranges[0][0], 0, marker_ranges[0][1], height),
            marker_boxes=[(x0, 0, x1, height) for x0, x1 in marker_ranges],
            rows=rows,
            safe_count=safe_count,
            explicit_count=explicit_count,
            neutral_count=neutral_count,
        )

    def _marker_ranges(self, width: int) -> List[Tuple[int, int]]:
        if self.options.marker_width > 0:
            x0 = clamp_int(self.options.marker_x, 0, max(0, width - 1))
            x1 = clamp_int(x0 + self.options.marker_width, x0 + 1, width)
            return [(x0, x1)]

        left_width = min(32, width)
        right_width = min(96, width)
        ranges = [(0, left_width)]
        right_start = max(left_width, width - right_width)
        if right_start < width:
            ranges.append((right_start, width))
        return ranges

    def _cluster_rows(self, row_counts: List[int]) -> List[Tuple[int, int, int]]:
        clusters: List[Tuple[int, int, int]] = []
        start: Optional[int] = None
        last_hit: Optional[int] = None
        peak = 0
        gap = 0
        threshold = max(1, self.options.min_row_content_pixels)
        max_gap = max(0, self.options.row_merge_gap)

        for y, count in enumerate(row_counts):
            if count >= threshold:
                if start is None:
                    start = y
                    peak = count
                else:
                    peak = max(peak, count)
                last_hit = y
                gap = 0
                continue

            if start is not None:
                gap += 1
                if gap > max_gap:
                    bottom = last_hit if last_hit is not None else y - gap
                    self._append_cluster(clusters, start, bottom, peak)
                    start = None
                    last_hit = None
                    peak = 0
                    gap = 0

        if start is not None:
            bottom = last_hit if last_hit is not None else len(row_counts) - 1
            self._append_cluster(clusters, start, bottom, peak)

        return clusters

    def _append_cluster(self, clusters: List[Tuple[int, int, int]], top: int, bottom: int, peak: int) -> None:
        height = bottom - top + 1
        if self.options.min_cluster_height <= height <= self.options.max_cluster_height:
            clusters.append((top, bottom, peak))

    def _count_marker_pixels(
        self, pixels, marker_ranges: List[Tuple[int, int]], top: int, bottom: int
    ) -> Tuple[int, int]:
        friend_pixels = 0
        hostile_pixels = 0
        for y in range(top, bottom + 1):
            for x0, x1 in marker_ranges:
                for x in range(x0, x1):
                    r, g, b = pixels[x, y]
                    if self._is_friend_pixel(r, g, b):
                        friend_pixels += 1
                    elif self._is_hostile_pixel(r, g, b):
                        hostile_pixels += 1
        return friend_pixels, hostile_pixels

    def _classify_row(self, friend_pixels: int, hostile_pixels: int) -> str:
        marker_threshold = max(1, self.options.min_pixels_per_row)
        if friend_pixels >= marker_threshold:
            return "safe"
        if hostile_pixels >= marker_threshold:
            return "hostile"
        if self.options.alert_white:
            return "neutral"
        return "safe"

    def _is_row_content_pixel(self, r: int, g: int, b: int) -> bool:
        luma = (r * 299 + g * 587 + b * 114) // 1000
        bright_text = luma >= 145 and (max(r, g, b) - min(r, g, b)) <= 95
        return bright_text or self._is_friend_pixel(r, g, b) or self._is_hostile_pixel(r, g, b)

    def _is_friend_pixel(self, r: int, g: int, b: int) -> bool:
        # EVE's standing icons are anti-aliased and can be quite dark after
        # transparency/background blending, so use relative color dominance
        # instead of only bright absolute thresholds.
        blue = b >= 85 and b >= r + 28 and b >= g + 14
        purple = r >= 70 and b >= 90 and r >= g + 12 and b >= g + 22
        green = g >= 85 and g >= r + 28 and g >= b + 18
        return blue or purple or green

    def _is_hostile_pixel(self, r: int, g: int, b: int) -> bool:
        red = False
        orange = False

        if self.options.alert_red:
            red = r >= 95 and r >= g + 28 and r >= b + 24

        if self.options.alert_orange:
            orange = (
                r >= 95
                and g >= 45
                and r >= g + 12
                and r >= b + 32
                and g >= b + 8
            )

        return red or orange


def make_debug_overlay(image, result: ThreatResult):
    if ImageDraw is None:
        return image

    overlay = image.copy().convert("RGB")
    draw = ImageDraw.Draw(overlay)
    for x0, y0, x1, y1 in result.marker_boxes:
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), outline=(255, 220, 0), width=1)
    for row in result.rows:
        if row.status == "safe":
            color = (0, 220, 120)
        elif row.status == "hostile":
            color = (255, 0, 0)
        else:
            color = (255, 145, 0)
        draw.rectangle((0, row.top, overlay.width - 1, row.bottom), outline=color, width=2)
    return overlay


def virtual_screen_bounds(root: tk.Tk) -> Tuple[int, int, int, int]:
    if mss is not None:
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[0]
                return monitor["left"], monitor["top"], monitor["width"], monitor["height"]
        except Exception:
            pass

    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class LocalGuardApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("720x760")
        self.root.minsize(680, 700)

        self.config = load_config()
        self.grabber: Optional[ScreenGrabber] = None
        self.monitoring = False
        self.hit_streak = 0
        self.clear_streak = 0
        self.alerted_count = 0
        self.last_alert_at = 0.0
        self.alert_active = False
        self.alert_popup = None
        self.alert_sound_job = None

        self.status_var = tk.StringVar(value="未开始")
        self.count_var = tk.StringVar(value="疑似威胁：0 行")

        self._make_vars()
        self._build_ui()
        self._apply_topmost()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        if PIL_IMPORT_ERROR is not None:
            self.log(f"缺少 Pillow：{PIL_IMPORT_ERROR}")
        if MSS_IMPORT_ERROR is not None:
            self.log("未安装 mss，将使用 Pillow 截图，速度可能慢一些。")

    def _make_vars(self) -> None:
        region = self.config["region"]
        scan = self.config["scan"]
        self.vars = {
            "x": tk.StringVar(value=str(region["x"])),
            "y": tk.StringVar(value=str(region["y"])),
            "width": tk.StringVar(value=str(region["width"])),
            "height": tk.StringVar(value=str(region["height"])),
            "interval_ms": tk.StringVar(value=str(scan["interval_ms"])),
            "marker_x": tk.StringVar(value=str(scan["marker_x"])),
            "marker_width": tk.StringVar(value=str(scan["marker_width"])),
            "min_pixels_per_row": tk.StringVar(value=str(scan["min_pixels_per_row"])),
            "min_row_content_pixels": tk.StringVar(value=str(scan["min_row_content_pixels"])),
            "row_merge_gap": tk.StringVar(value=str(scan["row_merge_gap"])),
            "min_cluster_height": tk.StringVar(value=str(scan["min_cluster_height"])),
            "max_cluster_height": tk.StringVar(value=str(scan["max_cluster_height"])),
            "required_frames": tk.StringVar(value=str(scan["required_frames"])),
            "clear_frames": tk.StringVar(value=str(scan["clear_frames"])),
            "cooldown_seconds": tk.StringVar(value=str(scan["cooldown_seconds"])),
            "alert_red": tk.BooleanVar(value=bool(scan["alert_red"])),
            "alert_orange": tk.BooleanVar(value=bool(scan["alert_orange"])),
            "alert_white": tk.BooleanVar(value=bool(scan["alert_white"])),
            "sound": tk.BooleanVar(value=bool(scan["sound"])),
            "sound_effect": tk.StringVar(value=str(scan["sound_effect"])),
            "popup": tk.BooleanVar(value=bool(scan["popup"])),
            "persistent_alert": tk.BooleanVar(value=bool(scan["persistent_alert"])),
            "topmost": tk.BooleanVar(value=bool(scan["topmost"])),
        }

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(
            outer,
            text="EVE 本地威胁行监控",
            font=("Microsoft YaHei UI", 16, "bold"),
        )
        title.pack(anchor="w")

        subtitle = ttk.Label(
            outer,
            text="蓝/紫/绿视为友方；红/橙或无友方标记的玩家行视为威胁。",
            foreground="#555555",
        )
        subtitle.pack(anchor="w", pady=(2, 10))

        region_frame = ttk.LabelFrame(outer, text="监控区域")
        region_frame.pack(fill="x", pady=(0, 10))
        self._grid_number_field(region_frame, "X", "x", 0, 0)
        self._grid_number_field(region_frame, "Y", "y", 0, 2)
        self._grid_number_field(region_frame, "宽", "width", 1, 0)
        self._grid_number_field(region_frame, "高", "height", 1, 2)

        ttk.Button(region_frame, text="框选本地列表区域", command=self.select_region).grid(
            row=0,
            column=4,
            rowspan=2,
            padx=10,
            pady=8,
            sticky="nsew",
        )
        region_frame.columnconfigure(5, weight=1)

        scan_frame = ttk.LabelFrame(outer, text="检测参数")
        scan_frame.pack(fill="x", pady=(0, 10))
        self._grid_number_field(scan_frame, "间隔(ms)", "interval_ms", 0, 0)
        self._grid_number_field(scan_frame, "标记列X", "marker_x", 0, 2)
        self._grid_number_field(scan_frame, "标记列宽", "marker_width", 0, 4)
        self._grid_number_field(scan_frame, "标记像素", "min_pixels_per_row", 1, 0)
        self._grid_number_field(scan_frame, "行内容像素", "min_row_content_pixels", 1, 2)
        self._grid_number_field(scan_frame, "行合并", "row_merge_gap", 1, 4)
        self._grid_number_field(scan_frame, "最小高度", "min_cluster_height", 2, 0)
        self._grid_number_field(scan_frame, "最大高度", "max_cluster_height", 2, 2)
        self._grid_number_field(scan_frame, "确认帧", "required_frames", 2, 4)
        self._grid_number_field(scan_frame, "清空帧", "clear_frames", 3, 0)
        self._grid_number_field(scan_frame, "冷却(s)", "cooldown_seconds", 3, 2)

        option_frame = ttk.LabelFrame(outer, text="报警选项")
        option_frame.pack(fill="x", pady=(0, 10))
        checks = [
            ("红色", "alert_red"),
            ("橙色", "alert_orange"),
            ("白/中立", "alert_white"),
            ("声音", "sound"),
            ("弹窗", "popup"),
            ("持续提醒", "persistent_alert"),
            ("窗口置顶", "topmost"),
        ]
        for index, (label, key) in enumerate(checks):
            ttk.Checkbutton(
                option_frame,
                text=label,
                variable=self.vars[key],
                command=self._apply_topmost if key == "topmost" else None,
            ).grid(row=index // 3, column=index % 3, sticky="w", padx=8, pady=6)

        status_frame = ttk.Frame(outer)
        status_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(status_frame, textvariable=self.status_var, font=("Microsoft YaHei UI", 11, "bold")).pack(
            side="left"
        )
        ttk.Label(status_frame, textvariable=self.count_var, foreground="#8a1f11").pack(side="right")

        button_frame = ttk.Frame(outer)
        button_frame.pack(fill="x", pady=(0, 10))
        self.start_button = ttk.Button(button_frame, text="开始监控", command=self.start_monitoring)
        self.start_button.pack(side="left", padx=(0, 8))
        self.stop_button = ttk.Button(button_frame, text="停止", command=self.stop_monitoring, state="disabled")
        self.stop_button.pack(side="left", padx=(0, 8))
        ttk.Button(button_frame, text="测试识别并保存截图", command=self.test_capture).pack(side="left", padx=(0, 8))
        ttk.Button(button_frame, text="测试声音", command=self.test_sound).pack(side="left", padx=(0, 8))
        self.ack_button = ttk.Button(button_frame, text="确认告警", command=self.acknowledge_alert, state="disabled")
        self.ack_button.pack(side="left", padx=(0, 8))
        ttk.Button(button_frame, text="保存配置", command=self.save_config_from_vars).pack(side="left", padx=(0, 8))
        ttk.Button(button_frame, text="打开配置目录", command=self.open_config_dir).pack(side="right")

        log_frame = ttk.LabelFrame(outer, text="日志")
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=12, wrap="word")
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.log(f"配置文件：{config_path()}")

    def _grid_number_field(self, parent, label: str, key: str, row: int, column: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="e", padx=(8, 4), pady=6)
        entry = ttk.Entry(parent, textvariable=self.vars[key], width=9)
        entry.grid(row=row, column=column + 1, sticky="w", padx=(0, 8), pady=6)

    def _apply_topmost(self) -> None:
        self.root.attributes("-topmost", bool(self.vars["topmost"].get()))

    def log(self, message: str) -> None:
        if not hasattr(self, "log_text"):
            return
        now = _dt.datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{now}] {message}\n")
        self.log_text.see("end")

    def region_from_vars(self) -> Region:
        return Region(
            x=parse_int(self.vars["x"].get(), 0),
            y=parse_int(self.vars["y"].get(), 0),
            width=parse_int(self.vars["width"].get(), 360, 20, 4000),
            height=parse_int(self.vars["height"].get(), 460, 20, 4000),
        ).normalized()

    def options_from_vars(self) -> DetectorOptions:
        return DetectorOptions(
            marker_x=parse_int(self.vars["marker_x"].get(), 0, 0, 2000),
            marker_width=parse_int(self.vars["marker_width"].get(), 0, 0, 4000),
            min_pixels_per_row=parse_int(self.vars["min_pixels_per_row"].get(), 6, 1, 500),
            min_row_content_pixels=parse_int(self.vars["min_row_content_pixels"].get(), 18, 1, 2000),
            row_merge_gap=parse_int(self.vars["row_merge_gap"].get(), 3, 0, 30),
            min_cluster_height=parse_int(self.vars["min_cluster_height"].get(), 3, 1, 100),
            max_cluster_height=parse_int(self.vars["max_cluster_height"].get(), 80, 1, 300),
            alert_red=bool(self.vars["alert_red"].get()),
            alert_orange=bool(self.vars["alert_orange"].get()),
            alert_white=bool(self.vars["alert_white"].get()),
        )

    def current_config(self) -> Dict:
        region = self.region_from_vars()
        scan = self.config["scan"].copy()
        scan["detector_version"] = DEFAULT_CONFIG["scan"]["detector_version"]
        for key in [
            "interval_ms",
            "marker_x",
            "marker_width",
            "min_pixels_per_row",
            "min_row_content_pixels",
            "row_merge_gap",
            "min_cluster_height",
            "max_cluster_height",
            "required_frames",
            "clear_frames",
            "cooldown_seconds",
        ]:
            scan[key] = parse_int(self.vars[key].get(), DEFAULT_CONFIG["scan"][key])
        for key in ["alert_red", "alert_orange", "alert_white", "sound", "popup", "persistent_alert", "topmost"]:
            scan[key] = bool(self.vars[key].get())
        scan["sound_effect"] = str(self.vars["sound_effect"].get() or "alarm")
        return {
            "region": {
                "x": region.x,
                "y": region.y,
                "width": region.width,
                "height": region.height,
            },
            "scan": scan,
        }

    def save_config_from_vars(self) -> None:
        self.config = self.current_config()
        save_config(self.config)
        self.log("配置已保存。")

    def select_region(self) -> None:
        left, top, width, height = virtual_screen_bounds(self.root)
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.28)
        overlay.configure(bg="black")
        overlay.geometry(f"{width}x{height}{left:+d}{top:+d}")

        canvas = tk.Canvas(overlay, cursor="crosshair", bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_text(
            24,
            24,
            anchor="nw",
            fill="white",
            font=("Microsoft YaHei UI", 18, "bold"),
            text="拖拽框选 EVE 本地成员列表区域，按 Esc 取消",
        )

        start: Dict[str, Optional[int]] = {"x": None, "y": None}
        rect_id: Dict[str, Optional[int]] = {"id": None}

        def to_canvas(x_root: int, y_root: int) -> Tuple[int, int]:
            return x_root - left, y_root - top

        def on_press(event) -> None:
            start["x"] = event.x_root
            start["y"] = event.y_root
            cx, cy = to_canvas(event.x_root, event.y_root)
            rect_id["id"] = canvas.create_rectangle(cx, cy, cx, cy, outline="#ff3333", width=2)

        def on_drag(event) -> None:
            if start["x"] is None or rect_id["id"] is None:
                return
            x0, y0 = to_canvas(start["x"], start["y"])
            x1, y1 = to_canvas(event.x_root, event.y_root)
            canvas.coords(rect_id["id"], x0, y0, x1, y1)

        def on_release(event) -> None:
            if start["x"] is None:
                overlay.destroy()
                return
            x0 = min(start["x"], event.x_root)
            y0 = min(start["y"], event.y_root)
            x1 = max(start["x"], event.x_root)
            y1 = max(start["y"], event.y_root)
            selected_width = x1 - x0
            selected_height = y1 - y0
            overlay.destroy()
            if selected_width < 20 or selected_height < 20:
                messagebox.showwarning(APP_NAME, "区域太小，请重新框选。")
                return
            self.vars["x"].set(str(x0))
            self.vars["y"].set(str(y0))
            self.vars["width"].set(str(selected_width))
            self.vars["height"].set(str(selected_height))
            self.save_config_from_vars()
            self.log(f"已选择区域：x={x0}, y={y0}, w={selected_width}, h={selected_height}")

        overlay.bind("<Escape>", lambda _event: overlay.destroy())
        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.focus_force()

    def start_monitoring(self) -> None:
        if PIL_IMPORT_ERROR is not None:
            messagebox.showerror(APP_NAME, "缺少 Pillow，请先安装依赖或运行打包脚本。")
            return

        self.save_config_from_vars()
        self.monitoring = True
        self.hit_streak = 0
        self.clear_streak = 0
        self.alerted_count = 0
        self.last_alert_at = 0.0
        self.grabber = ScreenGrabber()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set("监控中")
        self.log("开始监控。")
        self.root.after(50, self.scan_once)

    def stop_monitoring(self) -> None:
        self.monitoring = False
        self.acknowledge_alert(log_message=False)
        if self.grabber is not None:
            self.grabber.close()
            self.grabber = None
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_var.set("已停止")
        self.log("已停止。")

    def scan_once(self) -> None:
        if not self.monitoring:
            return

        interval = parse_int(self.vars["interval_ms"].get(), 700, 200, 10000)
        try:
            region = self.region_from_vars()
            options = self.options_from_vars()
            detector = ThreatDetector(options)
            if self.grabber is None:
                self.grabber = ScreenGrabber()
            image = self.grabber.grab(region)
            result = detector.analyze(image)
            self.handle_result(result)
        except Exception as exc:
            self.status_var.set("截图或识别失败")
            self.log(f"截图或识别失败：{exc}")

        self.root.after(interval, self.scan_once)

    def handle_result(self, result: ThreatResult) -> None:
        self.count_var.set(
            f"威胁 {result.count} 行（红橙 {result.explicit_count} / 白中立 {result.neutral_count}），友方 {result.safe_count}"
        )
        required_frames = parse_int(self.vars["required_frames"].get(), 2, 1, 20)
        clear_frames = parse_int(self.vars["clear_frames"].get(), 3, 1, 30)
        cooldown = parse_int(self.vars["cooldown_seconds"].get(), 8, 0, 3600)

        if result.count > 0:
            self.hit_streak += 1
            self.clear_streak = 0
            self.status_var.set(f"检测到威胁行，确认 {self.hit_streak}/{required_frames}")

            now = time.time()
            persistent = bool(self.vars["persistent_alert"].get())
            enough_frames = self.hit_streak >= required_frames
            cooled_down = (now - self.last_alert_at) >= cooldown
            new_or_more = result.count > self.alerted_count

            if enough_frames and cooled_down and (persistent or new_or_more):
                self.alerted_count = max(self.alerted_count, result.count)
                self.last_alert_at = now
                self.alert(result)
            return

        self.hit_streak = 0
        self.clear_streak += 1
        self.status_var.set("监控中，未发现威胁行")
        if self.clear_streak >= clear_frames and self.alerted_count:
            self.alerted_count = 0
            self.log("威胁行已清空。")

    def alert(self, result: ThreatResult) -> None:
        message = f"检测到威胁：{result.count} 行（红橙 {result.explicit_count}，白/中立 {result.neutral_count}）"
        self.log(message)
        if self.alert_active:
            self.status_var.set("告警中，等待确认")
            return

        self.alert_active = True
        self.ack_button.configure(state="normal")
        self.status_var.set("告警中，等待确认")
        if bool(self.vars["sound"].get()):
            self.start_alert_sound_loop()
        if bool(self.vars["popup"].get()):
            self.show_alert_popup(message)

    def start_alert_sound_loop(self) -> None:
        if not self.alert_active or not bool(self.vars["sound"].get()):
            return
        self.play_alert_sound()
        self.alert_sound_job = self.root.after(1200, self.start_alert_sound_loop)

    def stop_alert_sound_loop(self) -> None:
        if self.alert_sound_job is not None:
            try:
                self.root.after_cancel(self.alert_sound_job)
            except Exception:
                pass
            self.alert_sound_job = None
        if sys.platform == "win32":
            try:
                import winsound

                winsound.PlaySound(None, 0)
            except Exception:
                pass

    def acknowledge_alert(self, log_message: bool = True) -> None:
        was_active = self.alert_active
        self.alert_active = False
        self.stop_alert_sound_loop()
        try:
            self.ack_button.configure(state="disabled")
        except Exception:
            pass
        if self.alert_popup is not None:
            try:
                if self.alert_popup.winfo_exists():
                    self.alert_popup.destroy()
            except Exception:
                pass
            self.alert_popup = None
        if was_active and log_message:
            self.log("告警已确认，声音已停止。")
        if self.monitoring:
            self.status_var.set("监控中")

    def play_alert_sound(self) -> None:
        if sys.platform == "win32":
            try:
                import winsound

                winsound.PlaySound(ensure_alert_sound(), winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            except Exception as exc:
                self.log(f"播放告警音效失败，改用系统提示音：{exc}")
                try:
                    winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
                    return
                except Exception:
                    pass
        try:
            for delay in (0, 180, 360):
                self.root.after(delay, self.root.bell)
        except Exception:
            pass

    def test_sound(self) -> None:
        if not bool(self.vars["sound"].get()):
            self.log("声音开关已关闭，测试声音不会播放。")
            messagebox.showinfo(APP_NAME, "声音开关已关闭。勾选“声音”后再测试。")
            return
        self.log("播放测试告警音效。")
        self.play_alert_sound()

    def show_alert_popup(self, message: str) -> None:
        if self.alert_popup is not None:
            try:
                if self.alert_popup.winfo_exists():
                    self.alert_popup.lift()
                    return
            except Exception:
                self.alert_popup = None

        popup = tk.Toplevel(self.root)
        self.alert_popup = popup
        popup.title("EVE Local Guard")
        popup.attributes("-topmost", True)
        popup.resizable(False, False)
        popup.protocol("WM_DELETE_WINDOW", self.acknowledge_alert)
        frame = ttk.Frame(popup, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="本地出现疑似威胁", font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")
        ttk.Label(frame, text=message).pack(anchor="w", pady=(6, 10))
        ttk.Button(frame, text="确认并停止声音", command=self.acknowledge_alert).pack(anchor="e")
        popup.update_idletasks()
        x = self.root.winfo_rootx() + max(0, self.root.winfo_width() - popup.winfo_width() - 18)
        y = self.root.winfo_rooty() + 48
        popup.geometry(f"+{x}+{y}")

    def test_capture(self) -> None:
        if PIL_IMPORT_ERROR is not None:
            messagebox.showerror(APP_NAME, "缺少 Pillow，请先安装依赖或运行打包脚本。")
            return

        grabber = ScreenGrabber()
        try:
            region = self.region_from_vars()
            detector = ThreatDetector(self.options_from_vars())
            image = grabber.grab(region)
            result = detector.analyze(image)
            capture_path = os.path.join(app_data_dir(), "last_capture.png")
            debug_path = os.path.join(app_data_dir(), "last_debug.png")
            image.save(capture_path)
            make_debug_overlay(image, result).save(debug_path)
            summary = (
                f"威胁 {result.count} 行（红橙 {result.explicit_count} / 白中立 {result.neutral_count}），"
                f"友方 {result.safe_count}"
            )
            self.count_var.set(summary)
            self.log(f"测试完成：{summary}。截图：{capture_path}")
            self.log(f"调试图：{debug_path}")
            messagebox.showinfo(
                APP_NAME,
                f"识别完成：{summary}\n\n已保存：\n{capture_path}\n{debug_path}",
            )
        except Exception as exc:
            self.log(f"测试失败：{exc}")
            self.log(traceback.format_exc())
            messagebox.showerror(APP_NAME, f"测试失败：{exc}")
        finally:
            grabber.close()

    def open_config_dir(self) -> None:
        path = app_data_dir()
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}"')
        except Exception as exc:
            messagebox.showinfo(APP_NAME, f"配置目录：{path}\n\n无法自动打开：{exc}")

    def on_close(self) -> None:
        self.stop_monitoring()
        try:
            self.save_config_from_vars()
        except Exception:
            pass
        self.root.destroy()


def main() -> None:
    set_dpi_awareness()
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    LocalGuardApp(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            path = write_crash_log(exc)
            try:
                messagebox.showerror(APP_NAME, f"程序启动失败，错误已写入：\n{path}\n\n{exc}")
            except Exception:
                pass
        finally:
            raise
