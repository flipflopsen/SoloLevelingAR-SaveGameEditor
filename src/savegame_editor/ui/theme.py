"""Centralized semantic color tokens and Qt stylesheet generation."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccentTheme:
    """Colors applied to interactive states without changing status colors."""

    name: str
    primary: str
    hover: str
    subtle: str
    indicator: str


ACCENT_THEMES = (
    AccentTheme("Sleek Purple", "#8B5CF6", "#9D75FF", "#2B203F", "#A78BFA"),
    AccentTheme("Sleek Green", "#35B779", "#4BC98A", "#19372D", "#63D49A"),
    AccentTheme("Sleek Blue", "#489EE8", "#65B3F5", "#1B3041", "#7BC3F5"),
    AccentTheme("Sleek Red", "#D55B68", "#E67883", "#3B2025", "#ED8A93"),
)


def accent_theme(name: str) -> AccentTheme:
    """Return a known theme, falling back safely for old or invalid settings."""
    return next((theme for theme in ACCENT_THEMES if theme.name == name), ACCENT_THEMES[0])


def valid_hex_color(value: str) -> bool:
    """Return whether a value is an unambiguous six-digit CSS-style color."""
    return bool(re.fullmatch(r"#[0-9A-Fa-f]{6}", value.strip()))


def resolve_accent_theme(name: str, custom_color: str = "") -> AccentTheme:
    """Use a validated custom primary color or one of the established presets."""
    custom_color = custom_color.strip().upper()
    if not valid_hex_color(custom_color):
        return accent_theme(name)
    red = int(custom_color[1:3], 16)
    green = int(custom_color[3:5], 16)
    blue = int(custom_color[5:7], 16)
    return AccentTheme(
        "Custom",
        custom_color,
        _adjust_color(red, green, blue, 22),
        _adjust_color(red, green, blue, -92),
        _adjust_color(red, green, blue, 46),
    )


def _adjust_color(red: int, green: int, blue: int, amount: int) -> str:
    channels = (red, green, blue)
    return "#" + "".join(f"{max(0, min(255, channel + amount)):02X}" for channel in channels)


def status_warning_color() -> str:
    """Provide the semantic warning token for non-stylesheet paint operations."""
    return "#E69A48"


def application_stylesheet(theme_name: str, custom_color: str = "") -> str:
    """Build the application stylesheet from semantic base and accent tokens."""
    theme = resolve_accent_theme(theme_name, custom_color)
    return f"""
QWidget {{
    color: #F0F0F2; font-family: "Segoe UI"; font-size: 12px;
}}
QWidget#root {{ background: #171719; }}
QWidget#sidebar {{ background: #1B1B1D; border-right: 1px solid #303034; }}
QWidget#workspace {{ background: #151516; }}
QWidget#toolbar, QWidget#inspector, QWidget#contextHeader {{
    background: #202022; border: 1px solid #303034; border-radius: 5px;
}}
QLabel#brand {{ color: #F0F0F2; font-size: 13px; font-weight: 700; }}
QLabel#brandSubtle, QLabel#pathStatus, QLabel#detailLabel {{ color: #73737A; font-size: 11px; }}
QLabel#pageTitle {{ color: #F0F0F2; font-size: 19px; font-weight: 600; }}
QLabel#viewTitle {{ color: #F0F0F2; font-size: 15px; font-weight: 600; }}
QLabel#statusReady {{ color: #42BE7B; font-size: 11px; font-weight: 600; }}
QLabel#statusWarning {{ color: #E69A48; font-size: 11px; font-weight: 600; }}
QLabel#statusError {{ color: #E7626C; font-size: 11px; font-weight: 600; }}
QToolButton#navigation {{
    color: #A7A7AD; text-align: left; padding: 8px 9px; border: 0;
    border-left: 3px solid transparent; border-radius: 3px;
}}
QToolButton#navigation:hover {{ background: #29292C; color: #F0F0F2; }}
QToolButton#navigation:checked {{
    background: {theme.subtle}; border-left-color: {theme.indicator}; color: #F0F0F2;
}}
QPushButton, QToolButton#toolbarButton, QComboBox, QLineEdit {{
    background: #252527; color: #F0F0F2; border: 1px solid #303034;
    border-radius: 4px; padding: 6px 9px; min-height: 17px;
}}
QPushButton:hover, QToolButton#toolbarButton:hover, QComboBox:hover {{ background: #29292C; }}
QPushButton:disabled, QToolButton:disabled {{ color: #73737A; background: #202022; }}
QPushButton#primary {{ background: {theme.primary}; border-color: {theme.primary}; color: #FFFFFF; font-weight: 600; }}
QPushButton#primary:hover {{ background: {theme.hover}; border-color: {theme.hover}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {theme.indicator}; }}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QComboBox QAbstractItemView {{ background: #252527; border: 1px solid #303034; selection-background-color: {theme.subtle}; }}
QTableView {{
    background: #202022; alternate-background-color: #1C1C1E; border: 1px solid #303034;
    gridline-color: #303034; selection-background-color: {theme.subtle};
    selection-color: #F0F0F2; outline: 0;
}}
QTableView::item {{ padding: 5px 8px; border-bottom: 1px solid #29292C; }}
QTableView::item:hover {{ background: #29292C; }}
QTableView::item:selected {{ background: {theme.subtle}; }}
QHeaderView::section {{
    background: #252527; color: #A7A7AD; padding: 7px 8px; border: 0;
    border-right: 1px solid #303034; border-bottom: 1px solid #303034; font-weight: 600;
}}
QScrollBar:vertical {{ background: #171719; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #3A3A3E; min-height: 28px; border-radius: 4px; }}
QSplitter::handle {{ background: #303034; width: 1px; }}
QCheckBox {{ color: #A7A7AD; spacing: 6px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid #303034; background: #252527; border-radius: 3px; }}
QCheckBox::indicator:checked {{ background: {theme.primary}; border-color: {theme.primary}; }}
QDialog {{ background: #202022; }}
QDialog QWidget {{ background: transparent; }}
QDialog QLineEdit, QDialog QComboBox {{ background: #202022; }}
QDialog QLineEdit:focus, QDialog QComboBox:focus {{ background: #202022; }}
"""
