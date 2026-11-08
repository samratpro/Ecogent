"""
Design system for the Ecogent GUI: a dark "modern web app" look (Linear / Vercel style):
neutral slate surfaces, indigo accent, hairline borders, rounded cards, pill badges,
Segoe Fluent icons, and "rich buttons" (a clickable card with icon + title + meta text).

Theme tags are global DPG aliases - never reuse one as a widget tag.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import dearpygui.dearpygui as dpg

# --------------------------------------------------------------------------- palette
BG = (9, 11, 17)              # app background
SIDEBAR = (13, 16, 24)
SURFACE = (17, 21, 31)        # cards
SURFACE_2 = (26, 32, 46)      # raised / hover
SURFACE_3 = (36, 43, 61)      # pressed
INPUT = (12, 15, 23)
BORDER = (36, 43, 60)
BORDER_SOFT = (27, 33, 47)
TEXT = (241, 245, 249)
MUTED = (203, 213, 225)
SUBTLE = (172, 184, 202)      # secondary text (help lines, field labels): readable on dark surfaces
FAINT = (148, 163, 184)       # tertiary only (timestamps, placeholders)
PRIMARY = (99, 102, 241)      # indigo-500
PRIMARY_HOVER = (129, 140, 248)
PRIMARY_ACTIVE = (79, 70, 229)
PRIMARY_SOFT = (35, 36, 82)   # selected item background
SUCCESS = (74, 222, 128)
WARNING = (251, 191, 36)
DANGER = (248, 113, 113)
INFO = (56, 189, 248)
USER_BUBBLE = (32, 34, 78)
AGENT_BUBBLE = (22, 27, 40)

STATUS_COLORS = {
    "done": SUCCESS, "running": PRIMARY_HOVER, "planned": INFO, "partial": WARNING,
    "failed": DANGER, "error": DANGER, "stopped": FAINT, "new": FAINT,
}

# Segoe Fluent Icons / Segoe MDL2 Assets code points
ICONS = {
    "add": "\ue710", "search": "\ue721", "settings": "\ue713", "play": "\ue768", "stop": "\ue71a",
    "refresh": "\ue72c", "folder": "\ue8b7", "contact": "\ue77b", "clock": "\ue823", "send": "\ue724",
    "delete": "\ue74d", "chat": "\ue8bd", "doc": "\ue8a5", "list": "\ue8fd", "bolt": "\ue945",
    "chart": "\ue9d9", "globe": "\ue774", "info": "\ue946", "check": "\ue73e", "panel": "\ue89f",
    "save": "\ue74e", "open": "\ue8a7", "test": "\uebe8", "spark": "\ue734", "user": "\ue77b",
}

FONTS: dict[str, int] = {}
UI_SCALE = 1.0


def enable_dpi_awareness() -> float:
    """Call before the viewport exists. Without it Windows bitmap-stretches the whole window
    on any display scale other than 100% (blurry text). Returns the display scale (1.0 = 96 dpi)
    so fonts can be rasterized at the real pixel size instead."""
    global UI_SCALE
    if sys.platform != "win32":
        return UI_SCALE
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            return UI_SCALE
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
    except Exception:
        dpi = 96
    UI_SCALE = max(1.0, dpi / 96)
    return UI_SCALE


def load_fonts() -> None:
    folder = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    files = {
        "body": ("segoeui.ttf", 19),
        "semibold": ("seguisb.ttf", 19),
        "small": ("segoeui.ttf", 16),
        "label": ("seguisb.ttf", 15),
        "title": ("seguisb.ttf", 24),
        "h1": ("seguisb.ttf", 34),
        "h2": ("seguisb.ttf", 21),
        "stat": ("seguisb.ttf", 25),
        "mono": ("consola.ttf", 17),
    }
    with dpg.font_registry():
        for name, (file, size) in files.items():
            path = folder / file
            if path.exists():
                # Whole pixel sizes at the real DPI: fractional sizes rasterize soft.
                FONTS[name] = dpg.add_font(str(path), round(size * UI_SCALE))   # glyphs load on demand
        icon_file = next((folder / n for n in ("SegoeIcons.ttf", "segmdl2.ttf") if (folder / n).exists()), None)
        if icon_file:
            for name, size in (("icon", 18), ("icon_sm", 15), ("icon_lg", 26)):
                FONTS[name] = dpg.add_font(str(icon_file), round(size * UI_SCALE))
    if "body" in FONTS:
        dpg.bind_font(FONTS["body"])


def font(item, name: str):
    if name in FONTS:
        dpg.bind_item_font(item, FONTS[name])
    return item


def icon(name: str) -> str:
    """Icon glyph, or '' when no icon font is installed (non-Windows)."""
    return ICONS.get(name, "") if "icon" in FONTS else ""


# --------------------------------------------------------------------------- themes
def _button_theme(tag: str, base, hover, active, text=TEXT, align_left=False, rounding=8, pad=(14, 8),
                  border=None):
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, base)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, hover)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, active)
            dpg.add_theme_color(dpg.mvThemeCol_Text, text)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, rounding)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, *pad)
            if border:
                dpg.add_theme_color(dpg.mvThemeCol_Border, border)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            if align_left:
                dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0.0, 0.5)
        with dpg.theme_component(dpg.mvButton, enabled_state=False):
            dpg.add_theme_color(dpg.mvThemeCol_Button, SURFACE)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, SURFACE)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, SURFACE)
            dpg.add_theme_color(dpg.mvThemeCol_Text, (100, 114, 136))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, rounding)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, *pad)


def _child_theme(tag: str, bg, border=None, rounding=12, pad=(16, 14), spacing=None):
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, bg)
            dpg.add_theme_color(dpg.mvThemeCol_Border, border or bg)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, rounding)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, *pad)
            if spacing:
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, *spacing)


def setup_themes() -> None:
    with dpg.theme() as global_theme:
        with dpg.theme_component(dpg.mvAll):
            c = dpg.add_theme_color
            c(dpg.mvThemeCol_WindowBg, BG)
            c(dpg.mvThemeCol_ChildBg, SURFACE)
            c(dpg.mvThemeCol_PopupBg, SURFACE)
            c(dpg.mvThemeCol_ModalWindowDimBg, (2, 4, 10, 170))
            c(dpg.mvThemeCol_Border, BORDER)
            c(dpg.mvThemeCol_Text, TEXT)
            c(dpg.mvThemeCol_TextDisabled, (110, 124, 146))
            c(dpg.mvThemeCol_FrameBg, INPUT)
            c(dpg.mvThemeCol_FrameBgHovered, (16, 20, 31))
            c(dpg.mvThemeCol_FrameBgActive, (20, 25, 38))
            c(dpg.mvThemeCol_TitleBg, SURFACE)
            c(dpg.mvThemeCol_TitleBgActive, SURFACE)
            c(dpg.mvThemeCol_TitleBgCollapsed, SURFACE)
            c(dpg.mvThemeCol_Button, SURFACE_2)
            c(dpg.mvThemeCol_ButtonHovered, SURFACE_3)
            c(dpg.mvThemeCol_ButtonActive, (46, 55, 78))
            c(dpg.mvThemeCol_Header, SURFACE_2)
            c(dpg.mvThemeCol_HeaderHovered, SURFACE_3)
            c(dpg.mvThemeCol_HeaderActive, (46, 55, 78))
            c(dpg.mvThemeCol_Tab, (0, 0, 0, 0))
            c(dpg.mvThemeCol_TabHovered, SURFACE_2)
            c(dpg.mvThemeCol_TabActive, SURFACE_3)
            c(dpg.mvThemeCol_TabUnfocused, (0, 0, 0, 0))
            c(dpg.mvThemeCol_TabUnfocusedActive, SURFACE_2)
            c(dpg.mvThemeCol_CheckMark, PRIMARY_HOVER)
            c(dpg.mvThemeCol_SliderGrab, PRIMARY)
            c(dpg.mvThemeCol_SliderGrabActive, PRIMARY_HOVER)
            c(dpg.mvThemeCol_Separator, BORDER_SOFT)
            c(dpg.mvThemeCol_ResizeGrip, (0, 0, 0, 0))
            c(dpg.mvThemeCol_ScrollbarBg, (0, 0, 0, 0))
            c(dpg.mvThemeCol_ScrollbarGrab, (45, 55, 75))
            c(dpg.mvThemeCol_ScrollbarGrabHovered, (65, 78, 102))
            c(dpg.mvThemeCol_ScrollbarGrabActive, (90, 105, 130))
            c(dpg.mvThemeCol_TableHeaderBg, SURFACE_2)
            c(dpg.mvThemeCol_TableBorderStrong, BORDER)
            c(dpg.mvThemeCol_TableBorderLight, BORDER_SOFT)
            c(dpg.mvThemeCol_TableRowBg, (0, 0, 0, 0))
            c(dpg.mvThemeCol_TableRowBgAlt, (255, 255, 255, 6))
            c(dpg.mvThemeCol_TextSelectedBg, (99, 102, 241, 110))
            c(dpg.mvThemeCol_NavHighlight, PRIMARY)
            s = dpg.add_theme_style
            s(dpg.mvStyleVar_WindowPadding, 14, 14)
            s(dpg.mvStyleVar_FramePadding, 12, 8)
            s(dpg.mvStyleVar_ItemSpacing, 10, 10)
            s(dpg.mvStyleVar_ItemInnerSpacing, 8, 6)
            s(dpg.mvStyleVar_WindowRounding, 14)
            s(dpg.mvStyleVar_ChildRounding, 12)
            s(dpg.mvStyleVar_FrameRounding, 8)
            s(dpg.mvStyleVar_PopupRounding, 10)
            s(dpg.mvStyleVar_TabRounding, 8)
            s(dpg.mvStyleVar_GrabRounding, 8)
            s(dpg.mvStyleVar_ScrollbarRounding, 8)
            s(dpg.mvStyleVar_ScrollbarSize, 8)
            s(dpg.mvStyleVar_WindowBorderSize, 1)
            s(dpg.mvStyleVar_ChildBorderSize, 1)
            s(dpg.mvStyleVar_FrameBorderSize, 0)
            s(dpg.mvStyleVar_PopupBorderSize, 1)
            s(dpg.mvStyleVar_WindowTitleAlign, 0.0, 0.5)
            s(dpg.mvStyleVar_CellPadding, 10, 8)
        # Text inputs get a hairline border so they read as fields on any surface.
        with dpg.theme_component(dpg.mvInputText):
            dpg.add_theme_color(dpg.mvThemeCol_Border, BORDER)
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
        for comp in (dpg.mvCombo, dpg.mvInputInt, dpg.mvInputFloat):
            with dpg.theme_component(comp):
                dpg.add_theme_color(dpg.mvThemeCol_Border, BORDER)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
        # Checkboxes: a visible box (border + lighter fill) and a bright tick; smaller padding = smaller box.
        with dpg.theme_component(dpg.mvCheckbox):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, SURFACE_2)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, SURFACE_3)
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (46, 55, 78))
            dpg.add_theme_color(dpg.mvThemeCol_Border, (90, 105, 130))
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark, (255, 255, 255))
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 4, 4)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 4)
    dpg.bind_theme(global_theme)

    _button_theme("btn_primary", PRIMARY, PRIMARY_HOVER, PRIMARY_ACTIVE, text=(255, 255, 255))
    _button_theme("btn_secondary", SURFACE_2, SURFACE_3, (46, 55, 78), border=BORDER)
    _button_theme("btn_ghost", (0, 0, 0, 0), SURFACE_2, SURFACE_3, text=MUTED)
    _button_theme("btn_danger", (69, 26, 36), (127, 29, 29), (153, 27, 27), text=(254, 202, 202))
    _button_theme("btn_icon", (0, 0, 0, 0), SURFACE_2, SURFACE_3, text=MUTED, pad=(8, 6))
    _button_theme("nav_item", (0, 0, 0, 0), SURFACE_2, SURFACE_3, align_left=True, pad=(12, 8))
    _button_theme("task_item", (0, 0, 0, 0), SURFACE_2, SURFACE_3, align_left=True, rounding=10, pad=(12, 10))
    _button_theme("task_item_active", PRIMARY_SOFT, (42, 44, 98), (50, 52, 112), align_left=True,
                  rounding=10, pad=(12, 10))
    _button_theme("type_card", INPUT, SURFACE_2, SURFACE_3, rounding=12, border=BORDER)
    _button_theme("type_card_active", PRIMARY_SOFT, (42, 44, 98), (50, 52, 112), rounding=12, border=PRIMARY)
    _button_theme("avatar_user", SURFACE_3, SURFACE_3, SURFACE_3, text=MUTED, rounding=18, pad=(0, 0))
    _button_theme("avatar_agent", PRIMARY, PRIMARY, PRIMARY, text=(255, 255, 255), rounding=18, pad=(0, 0))
    for name, color in (("pill_ok", SUCCESS), ("pill_busy", PRIMARY_HOVER), ("pill_err", DANGER),
                        ("pill_info", MUTED), ("pill_warn", WARNING)):
        bg = tuple(int(v * 0.18) for v in color)
        _button_theme(name, bg, bg, bg, text=color, rounding=20, pad=(12, 4))

    for status, color in STATUS_COLORS.items():
        _button_theme(f"dot_{status}", color, color, color, rounding=4, pad=(0, 0))

    _child_theme("card", SURFACE, BORDER_SOFT)
    _child_theme("sidebar", SIDEBAR, BORDER_SOFT, rounding=14, pad=(12, 14), spacing=(8, 8))
    _child_theme("topbar", SURFACE, BORDER_SOFT, rounding=14, pad=(18, 12))
    _child_theme("bubble_user", USER_BUBBLE, (55, 56, 140), rounding=14, pad=(14, 10))
    _child_theme("bubble_agent", AGENT_BUBBLE, BORDER_SOFT, rounding=14, pad=(14, 10))
    _child_theme("composer", INPUT, BORDER, rounding=14, pad=(12, 10))
    _child_theme("stat", INPUT, BORDER_SOFT, rounding=10, pad=(12, 8))
    _child_theme("tile", INPUT, BORDER_SOFT, rounding=10, pad=(12, 8), spacing=(4, 2))
    _child_theme("flat", (0, 0, 0, 0), (0, 0, 0, 0), rounding=0, pad=(0, 0))
    _child_theme("flat_pad", (0, 0, 0, 0), (0, 0, 0, 0), rounding=0, pad=(6, 6))
    _child_theme("list", (0, 0, 0, 0), (0, 0, 0, 0), rounding=0, pad=(0, 0), spacing=(6, 4))
    with dpg.theme(tag="dialog"):
        with dpg.theme_component(dpg.mvWindowAppItem):
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 22, 18)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 10, 10)
            dpg.add_theme_color(dpg.mvThemeCol_Border, BORDER)
    with dpg.theme(tag="tight"):
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 6, 0)

    # Selectable text (read-only input that looks like a plain label): no frame, no padding.
    with dpg.theme(tag="text_select"):
        with dpg.theme_component(dpg.mvInputText):
            for col in (dpg.mvThemeCol_FrameBg, dpg.mvThemeCol_FrameBgHovered, dpg.mvThemeCol_FrameBgActive):
                dpg.add_theme_color(col, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_Text, TEXT)
            dpg.add_theme_color(dpg.mvThemeCol_TextSelectedBg, (99, 102, 241, 140))
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 0, 2)
            dpg.add_theme_style(dpg.mvStyleVar_ScrollbarSize, 0)
    _button_theme("btn_copy", (0, 0, 0, 0), SURFACE_2, SURFACE_3, text=FAINT, rounding=6, pad=(6, 1))

    # Composer input: borderless and transparent so the composer card is the visible field.
    with dpg.theme(tag="input_bare"):
        with dpg.theme_component(dpg.mvInputText):
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (0, 0, 0, 0))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (0, 0, 0, 0))
            dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 4, 6)


# --------------------------------------------------------------------------- helpers
def section_label(text: str, parent=0):
    kw = {"parent": parent} if parent else {}
    return font(dpg.add_text(text.upper(), color=SUBTLE, **kw), "label")


def rich_button(parent, height: int, theme: str, callback=None, user_data=None, width: int = -1):
    """A full-size button inside a borderless child window; add content on top with put_*.
    Returns (card, button). Clicks anywhere on the card hit the button."""
    card = dpg.add_child_window(parent=parent, width=width, height=height, border=False, no_scrollbar=True)
    dpg.bind_item_theme(card, "flat")
    btn = dpg.add_button(parent=card, label="", width=-1, height=height, pos=[0, 0],
                         callback=callback, user_data=user_data)
    dpg.bind_item_theme(btn, theme)
    return card, btn


def put_text(card, text: str, x: int, y: int, font_name: str = "body", color=TEXT, **kw):
    return font(dpg.add_text(text, parent=card, pos=[x, y], color=color, **kw), font_name)


def put_icon(card, name: str, x: int, y: int, color=MUTED, size: str = "icon"):
    glyph = icon(name)
    return font(dpg.add_text(glyph, parent=card, pos=[x, y], color=color), size) if glyph else None


def put_dot(card, x: int, y: int, status: str, size: int = 8, **kw):
    """Small status dot (a tiny round button so it never shifts the card layout)."""
    name = f"dot_{status}" if status in STATUS_COLORS else "dot_new"
    b = dpg.add_button(label="", parent=card, pos=[x, y], width=size, height=size, **kw)
    dpg.bind_item_theme(b, name)
    return b


def icon_button(name: str, tooltip: str = "", callback=None, theme: str = "btn_icon", width: int = 36,
                height: int = 34, parent=0, fallback: str = "", **kw):
    """Icon-only button (falls back to text when the icon font is missing)."""
    glyph = icon(name)
    pkw = {"parent": parent} if parent else {}
    b = dpg.add_button(label=glyph or fallback or name, width=width if glyph else 0, height=height,
                       callback=callback, **pkw, **kw)
    dpg.bind_item_theme(b, theme)
    if glyph:
        font(b, "icon")
    if tooltip:
        with dpg.tooltip(b):
            dpg.add_text(tooltip)
    return b


def truncate(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "\u2026"
