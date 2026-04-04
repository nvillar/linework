"""Shared constants for the linework package."""

from __future__ import annotations

import re

DEFAULT_CANVAS_WIDTH = 800
DEFAULT_CANVAS_HEIGHT = 800
DEFAULT_CANVAS_BACKGROUND = "#FFFFFF"

HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")
