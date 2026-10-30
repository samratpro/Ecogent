"""
Design system for the Ecogent GUI: a dark "web dashboard" look
(slate surfaces, indigo accent, rounded cards, pill badges, chat bubbles).
"""

from __future__ import annotations

import os
from pathlib import Path

import dearpygui.dearpygui as dpg

# --------------------------------------------------------------------------- palette (Tailwind-like)
BG = (11, 15, 25)            # app background
SIDEBAR = (15, 20, 33)
SURFACE = (22, 28, 45)       # cards
SURFACE_2 = (31, 39, 60)     # raised / hover
INPUT = (14, 19, 31)
BORDER = (44, 54, 78)
TEXT = (241, 245, 249)        # near-white body text
MUTED = (203, 213, 225)       # secondary text (high contrast on dark)
FAINT = (163, 177, 198)       # hints / labels, still readable
PRIMARY = (99, 102, 241)     # indigo-500
PRIMARY_HOVER = (129, 140, 248)
PRIMARY_ACTIVE = (79, 70, 229)
SUCCESS = (74, 222, 128)
WARNING = (251, 191, 36)
DANGER = (248, 113, 113)
USER_BUBBLE = (49, 46, 129)  # indigo-900
AGENT_BUBBLE = (30, 38, 58)

STATUS_COLORS = {
    "done": SUCCESS, "running": PRIMARY_HOVER, "planned": (56, 189, 248), "partial": WARNING,
    "failed": DANGER, "error": DANGER, "stopped": FAINT, "new": FAINT,
}

FONTS: dict[str, int] = {}


def load_fonts() -> None:
    folder = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    files = {
        "body": ("segoeui.ttf", 19),
        "semibold": ("seguisb.ttf", 19),
        "small": ("segoeui.ttf", 16),
        "label": ("seguisb.ttf", 15),
        "title": ("seguisb.ttf", 24),
        "h2": ("seguisb.ttf", 20),
        "stat": ("seguisb.ttf", 23),
        "mono": ("consola.ttf", 17),
    }
    with dpg.font_registry():
        for name, (file, size) in files.items():
            path = folder / file
            if path.exists():
                FONTS[name] = dpg.add_font(str(path), size)
    if "body" in FONTS:
        dpg.bind_font(FONTS["body"])


def font(item, name: str):
    if name in FONTS:
        dpg.bind_item_font(item, FONTS[name])
    return item


def _button_theme(tag: str, base, hover, active, text=TEXT, align_left=False, rounding=8, pad=(14, 8)):
    with dpg.theme(tag=tag):
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button, base)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, hover)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, active)
            dpg.add_theme_color(dpg.mvThemeCol_Text, text)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, rounding)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, *pad)
            if align_left:
                dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0.0, 0.5)
        with dpg.theme_component(dpg.mvButton, enabled_state=False):
            dpg.add_theme_color(dpg.mvThemeCol_Button, SURFACE)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, SURFACE)
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, SURFACE)
            dpg.add_theme_color(dpg.mvThemeCol_Text, (120, 134, 156))
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
            c(dpg.mvThemeCol_ModalWindowDimBg, (0, 0, 0, 150))
            c(dpg.mvThemeCol_Border, BORDER)
            c(dpg.mvThemeCol_Text, TEXT)
            c(dpg.mvThemeCol_TextDisabled, (130, 144, 166))
            c(dpg.mvThemeCol_FrameBg, INPUT)
            c(dpg.mvThemeCol_FrameBgHovered, (20, 27, 44))
            c(dpg.mvThemeCol_FrameBgActive, (24, 32, 52))
            c(dpg.mvThemeCol_TitleBg, SIDEBAR)
            c(dpg.mvThemeCol_TitleBgActive, SURFACE_2)
            c(dpg.mvThemeCol_TitleBgCollapsed, SIDEBAR)
            c(dpg.mvThemeCol_Button, SURFACE_2)
            c(dpg.mvThemeCol_ButtonHovered, (45, 56, 84))
            c(dpg.mvThemeCol_ButtonActive, (55, 68, 100))
            c(dpg.mvThemeCol_Header, SURFACE_2)
            c(dpg.mvThemeCol_HeaderHovered, (45, 56, 84))
            c(dpg.mvThemeCol_HeaderActive, (55, 68, 100))
            c(dpg.mvThemeCol_Tab, SURFACE)
            c(dpg.mvThemeCol_TabHovered, SURFACE_2)
            c(dpg.mvThemeCol_TabActive, PRIMARY_ACTIVE)
            c(dpg.mvThemeCol_TabUnfocused, SURFACE)
            c(dpg.mvThemeCol_TabUnfocusedActive, SURFACE_2)
            c(dpg.mvThemeCol_CheckMark, PRIMARY_HOVER)
            c(dpg.mvThemeCol_SliderGrab, PRIMARY)
            c(dpg.mvThemeCol_SliderGrabActive, PRIMARY_HOVER)
            c(dpg.mvThemeCol_Separator, BORDER)
            c(dpg.mvThemeCol_ScrollbarBg, (0, 0, 0, 0))
            c(dpg.mvThemeCol_ScrollbarGrab, (51, 65, 85))
            c(dpg.mvThemeCol_ScrollbarGrabHovered, (71, 85, 105))
            c(dpg.mvThemeCol_ScrollbarGrabActive, (100, 116, 139))
            c(dpg.mvThemeCol_TableHeaderBg, SURFACE_2)
            c(dpg.mvThemeCol_TableBorderStrong, BORDER)
            c(dpg.mvThemeCol_TableBorderLight, (36, 45, 66))
            c(dpg.mvThemeCol_TableRowBg, (0, 0, 0, 0))
            c(dpg.mvThemeCol_TableRowBgAlt, (255, 255, 255, 8))
            c(dpg.mvThemeCol_TextSelectedBg, (99, 102, 241, 110))
            c(dpg.mvThemeCol_NavHighlight, PRIMARY)
            s = dpg.add_theme_style
            s(dpg.mvStyleVar_WindowPadding, 16, 16)
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
            s(dpg.mvStyleVar_ScrollbarSize, 10)
            s(dpg.mvStyleVar_WindowBorderSize, 1)
            s(dpg.mvStyleVar_ChildBorderSize, 1)
            s(dpg.mvStyleVar_FrameBorderSize, 0)
            s(dpg.mvStyleVar_WindowTitleAlign, 0.0, 0.5)
            s(dpg.mvStyleVar_CellPadding, 10, 8)
    dpg.bind_theme(global_theme)

    _button_theme("btn_primary", PRIMARY, PRIMARY_HOVER, PRIMARY_ACTIVE, text=(255, 255, 255))
    _button_theme("btn_secondary", SURFACE_2, (45, 56, 84), (55, 68, 100))
    _button_theme("btn_ghost", (0, 0, 0, 0), SURFACE_2, (45, 56, 84), text=TEXT)
    _button_theme("btn_danger", (69, 26, 36), (127, 29, 29), (153, 27, 27), text=(254, 202, 202))
    _button_theme("task_item", (0, 0, 0, 0), SURFACE_2, (45, 56, 84), align_left=True, rounding=10, pad=(12, 10))
    _button_theme("task_item_active", (40, 42, 92), (49, 52, 110), (56, 58, 125), align_left=True, rounding=10, pad=(12, 10))
    for name, color in (("pill_ok", SUCCESS), ("pill_busy", PRIMARY_HOVER), ("pill_err", DANGER), ("pill_info", MUTED)):
        bg = tuple(int(v * 0.22) for v in color)
        _button_theme(name, bg, bg, bg, text=color, rounding=20, pad=(12, 4))

    _child_theme("card", SURFACE, BORDER)
    _child_theme("sidebar", SIDEBAR, (26, 33, 52), rounding=14)
    _child_theme("header", SIDEBAR, (26, 33, 52), rounding=14, pad=(18, 12))
    _child_theme("bubble_user", USER_BUBBLE, (67, 56, 202), rounding=14, pad=(14, 10))
    _child_theme("bubble_agent", AGENT_BUBBLE, BORDER, rounding=14, pad=(14, 10))
    _child_theme("stat", INPUT, BORDER, rounding=10, pad=(12, 8))
    _child_theme("tile", INPUT, BORDER, rounding=10, pad=(12, 8), spacing=(4, 2))
    _child_theme("flat", (0, 0, 0, 0), (0, 0, 0, 0), rounding=0, pad=(0, 0))


def section_label(text: str, parent=0):
    kw = {"parent": parent} if parent else {}
    return font(dpg.add_text(text.upper(), color=FAINT, **kw), "label")
