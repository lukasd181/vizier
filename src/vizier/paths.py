"""Where Civ 6 and Claude Desktop keep their files, per platform.

macOS paths were checked on a real install. Windows and Linux paths follow
civ6-mcp's tested save locations (the Mods folder sits next to Saves) and the
usual AppOptions locations; they haven't been verified on a real machine yet,
so every path can be overridden with an environment variable and `doctor`
lists everything it tried.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

CIV = "Sid Meier's Civilization VI"


@dataclass(frozen=True)
class CivPaths:
    platform: str  # mac | windows | linux
    app_options: list[Path]  # candidates, most likely first
    mods_dir: list[Path]
    claude_desktop_config: Path


def platform_key() -> str:
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def civ_paths() -> CivPaths:
    home = Path.home()
    plat = platform_key()
    if plat == "mac":
        base = home / "Library" / "Application Support" / CIV
        app = [base / "Firaxis Games" / CIV / "AppOptions.txt"]
        mods = [base / CIV / "Mods"]
        claude = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif plat == "windows":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        docs = home / "Documents" / "My Games" / CIV
        app = [local / "Firaxis Games" / CIV / "AppOptions.txt", docs / "AppOptions.txt"]
        mods = [docs / "Mods"]
        claude = roaming / "Claude" / "claude_desktop_config.json"
    else:
        base = home / ".local" / "share" / "aspyr-media" / CIV
        app = [base / "AppOptions.txt"]
        mods = [base / "Mods"]
        claude = home / ".config" / "Claude" / "claude_desktop_config.json"

    if os.environ.get("VIZIER_APPOPTIONS"):
        app = [Path(os.environ["VIZIER_APPOPTIONS"])]
    if os.environ.get("VIZIER_MODS_DIR"):
        mods = [Path(os.environ["VIZIER_MODS_DIR"])]
    return CivPaths(plat, app, mods, claude)


def first_existing(paths: list[Path]) -> Path | None:
    return next((p for p in paths if p.exists()), None)


def bundled_mod_dir() -> Path | None:
    """The VizierAlerts mod: packaged inside the wheel, or in the repo checkout."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "mod" / "VizierAlerts", here.parents[1] / "mod" / "VizierAlerts"):
        if (candidate / "VizierAlerts.modinfo").exists():
            return candidate
    return None
