"""lib_plot_themes.py — shared theming for General_tools visual scripts.

Single source of truth for PALETTE + FONT + NEUTRAL-color theming, imported by
gantt.py and subway.py so the two stay a matched set. Dependency-light (only
matplotlib.font_manager, lazily) so it loads in any tool's environment.

HOUSE DEFAULT (applies to every tool that uses this lib, incl. future ones)
---------------------------------------------------------------------------
Figures are TRANSPARENT-background + DUAL-SAFE palette by default, so they
blend onto ANY backdrop:
  * neutrals(theme) defaults transparent=True  → background + panel fills are
    fully transparent (no baked white/black box, no grey-frame risk).
  * data_palette() defaults to the 'dual' palette → saturated mid-luminance
    hues (red/mustard/green/blue/…) that stay legible on both light and dark,
    so the DATA colors stay CONSTANT across variants and never need to flip.
  * Only the INK flips: a static image can't have text legible on both pure
    white AND pure black (and Plotly can't outline text), so each tool emits
    TWO variants via theme — `_white` = dark ink (place on a light background),
    `_black` = light ink (place on a dark background). Loop both for full cover.
A tool that wants a baked solid background instead passes transparent=False.

Mirrors the conventions of the Riboseq downstream/bin/lib_plot_themes.py:
white/black themes, colourblind-safe palette option, installed-font resolution
with a quiet DejaVu fallback.

Concepts
--------
THEME    "light"/"dark" — now the INK target (dark ink for light backgrounds,
         light ink for dark). "white"/"black" are aliases; normalize_theme() maps.
PALETTE  "dual" (DEFAULT — dual-safe, constant across variants), or "editorial"
         / "okabe-ito" (each has a light + brightened dark variant; for solid-bg
         use). data_palette(name="dual", theme) -> list[str].
FONT     "sans" (Arial/Helvetica house style — default) or "serif" (Georgia
         masthead + sans body — editorial). resolve_fonts(choice) returns the
         installed face names plus CSS fallback strings.
NEUTRALS shared structural colors per theme (paper, ink, grid, node/file, …).
         neutrals(theme, transparent=True) -> dict; tools read the keys they need.

API
---
  normalize_theme(s)               -> "light" | "dark"
  bg_name(theme)                   -> "white" | "black"  (file-suffix convention)
  data_palette(name="dual", theme) -> list[str]
  neutrals(theme, transparent=True)-> dict[str, str]
  resolve_fonts(choice)            -> {"title","body","title_css","body_css"}
"""
from __future__ import annotations

import sys


def _warn(msg: str) -> None:
    print(f"lib_plot_themes: warning: {msg}", file=sys.stderr)


# ── Theme normalisation ──────────────────────────────────────────────────────
def normalize_theme(theme: str) -> str:
    t = (theme or "light").lower()
    if t in ("white", "light"):
        return "light"
    if t in ("black", "dark"):
        return "dark"
    return "light"


def bg_name(theme: str) -> str:
    """File-suffix name following the Riboseq `_white`/`_black` convention."""
    return "white" if normalize_theme(theme) == "light" else "black"


# ── Palettes ─────────────────────────────────────────────────────────────────
# Editorial: mostly-cool field led by one warm terracotta accent; dark variant
# brightens every hue so it stays vivid on charcoal.
_EDITORIAL = {
    "light": ["#B5654A", "#3A6E8F", "#5C8A6E", "#C9972F", "#3D405B",
              "#6E7B8B", "#8A6D5B", "#A6577C", "#5B6F47", "#9A8A55"],
    "dark":  ["#D98E6A", "#6BA3C4", "#84B89A", "#E0B252", "#9CA0D8",
              "#9FB0C0", "#BFA48E", "#D08CB0", "#9DB37A", "#CBBA86"],
}
# Okabe-Ito 8-class colourblind-safe set (matches the Riboseq lib's
# CATEGORICAL_COLORS_*), ordered for maximum perceptual distance between
# adjacent classes. Distinguishable under deuteranopia/protanopia/tritanopia.
_OKABE_ITO = {
    "light": ["#E69F00", "#56B4E9", "#009E73", "#CC79A7",
              "#0072B2", "#D55E00", "#F0E442", "#000000"],
    "dark":  ["#FFB347", "#7DCFFC", "#7CCFBA", "#E0A8C0",
              "#56B4E9", "#E69F00", "#F7EE8A", "#FFFFFF"],
}
# Dual-safe: saturated, mid-luminance hues that stay legible on BOTH a bright
# and a dark background, so a transparent figure's data colors DON'T have to flip
# between its light-ink and dark-ink variants — only the text/strokes flip. Tuned
# to roughly 0.25–0.40 relative luminance (dark enough to read on white, bright
# enough to read on black). Same list for both themes.
_DUAL_SAFE_LIST = [
    "#E54B4B",  # red
    "#D98E04",  # mustard / amber
    "#2FA24E",  # green
    "#3F82C8",  # blue
    "#9B5DE5",  # purple
    "#17A398",  # teal
    "#EC7A30",  # orange
    "#D957A0",  # magenta / pink
    "#7E8B33",  # olive
    "#5566CC",  # indigo
]
_DUAL_SAFE = {"light": _DUAL_SAFE_LIST, "dark": _DUAL_SAFE_LIST}
PALETTES = {"editorial": _EDITORIAL, "okabe-ito": _OKABE_ITO, "dual": _DUAL_SAFE}


def data_palette(name: str = "dual", theme: str = "light") -> list:
    """Return the category/track color list for a palette name + theme.

    Defaults to the dual-safe palette (the house default — constant across the
    light-ink and dark-ink variants so transparent figures read on any backdrop).
    """
    pal = PALETTES.get(name)
    if pal is None:
        _warn(f"unknown palette {name!r}; using 'editorial'")
        pal = _EDITORIAL
    return list(pal[normalize_theme(theme)])


# ── Shared neutral structural colors (union of both tools' needs) ────────────
_NEUTRALS = {
    "light": {
        "paper": "#FCFCFB", "plot_bg": "white",
        "ink": "#2B2B2B", "muted": "#6B6B6B", "faint": "#9A9A9A",
        "title_ink": "#1A1A1A", "axis_tick": "#8A8A8A",
        "grid": "#F0F0F0", "baseline": "#D8D8D8",
        "today": "#A6202C", "milestone": "#2B2B2B", "marker_edge": "white",
        "hover_bg": "rgba(255,255,255,0.96)", "hover_border": "#D8D8D8",
        "slider_bg": "#F7F3EF", "slider_border": "#E4DAD2",
        # subway structural
        "workflow_bg": "#FAFAF8", "workflow_title": "#1A1A1A",
        "accent_tick": "#C9C9C9", "node_fill": "#FFFFFF", "node_border": "#9AA3A8",
        "node_text": "#2B2B2B", "node_sub": "#6B6B6B", "phase_text": "#8A8A8A",
        "phase_rule": "#E2E2E2", "phase_guide": "#EEEEEE", "title_text": "#1A1A1A",
        "source_text": "#9A9A9A", "file_fill": "#FBF6E9", "file_border": "#9A8A55",
        "file_fold": "#EFE3C2",
    },
    "dark": {
        "paper": "#171A1F", "plot_bg": "#1B1F26",
        "ink": "#E6E4DF", "muted": "#A6A39C", "faint": "#6E6C68",
        "title_ink": "#F2F0EB", "axis_tick": "#8A8F98",
        "grid": "#2A2E36", "baseline": "#3A3F49",
        "today": "#FF6B5E", "milestone": "#E6E4DF", "marker_edge": "#1B1F26",
        "hover_bg": "rgba(30,34,42,0.97)", "hover_border": "#3A3F49",
        "slider_bg": "#22262E", "slider_border": "#343A44",
        # subway structural
        "workflow_bg": "#1E222A", "workflow_title": "#F2F0EB",
        "accent_tick": "#3A3F49", "node_fill": "#232830", "node_border": "#444B55",
        "node_text": "#E6E4DF", "node_sub": "#A6A39C", "phase_text": "#8A8F98",
        "phase_rule": "#2E333C", "phase_guide": "#262B33", "title_text": "#F2F0EB",
        "source_text": "#6E6C68", "file_fill": "#2A2A20", "file_border": "#8A7A45",
        "file_fold": "#3A3522",
    },
}


# Fill colors zeroed in transparent mode (backgrounds + panel/marker fills). The
# ink/stroke/grid/text colors are intentionally NOT here — those flip per theme.
_TRANSPARENT_KEYS = ("paper", "plot_bg", "node_fill", "workflow_bg",
                     "file_fill", "file_fold", "marker_edge")


def neutrals(theme: str, transparent: bool = True) -> dict:
    """Return a fresh copy of the structural neutral colors for the theme.

    transparent=True (the HOUSE DEFAULT) zeroes the BACKGROUND / panel-fill colors
    (paper, plot area, node / workflow / file fills, marker edge) to fully
    transparent so the figure blends onto any backdrop. The ink/stroke/grid/text
    colors stay per-theme — that half must flip between the light-ink and
    dark-ink variants of a figure. Pass transparent=False for a baked solid bg.
    """
    d = dict(_NEUTRALS[normalize_theme(theme)])
    if transparent:
        for k in _TRANSPARENT_KEYS:
            d[k] = "rgba(0,0,0,0)"
    return d


# ── Font resolution (installed-or-fallback, quiet) ───────────────────────────
def _available_fonts() -> set:
    try:
        import matplotlib.font_manager as fm
        return {f.name for f in fm.fontManager.ttflist}
    except Exception:
        return set()


def _pick(preferred: list, default: str) -> str:
    avail = _available_fonts()
    for name in preferred:
        if name in avail:
            return name
    return default


def resolve_fonts(choice: str = "sans") -> dict:
    """Resolve the title + body faces for a font choice.

    'sans'  → Arial/Helvetica house style (title AND body sans; title bold).
    'serif' → Georgia masthead + sans body (the editorial identity).

    Returns installed face NAMES (for matplotlib `family=`) plus CSS fallback
    strings (for plotly). A missing preferred face falls back to DejaVu with a
    single warning — never a silent wrong-type render.
    """
    sans = _pick(["Helvetica Neue", "Arial", "Helvetica", "Liberation Sans"],
                 "DejaVu Sans")
    sans_css = f"{sans}, Arial, Helvetica, sans-serif"
    if sans == "DejaVu Sans":
        _warn("Arial/Helvetica not installed; body falls back to DejaVu Sans")

    if choice == "serif":
        serif = _pick(["Georgia", "Times New Roman", "Liberation Serif"],
                      "DejaVu Serif")
        if serif == "DejaVu Serif":
            _warn("Georgia/Times not installed; titles fall back to DejaVu Serif")
        return {"title": serif, "body": sans,
                "title_css": f'{serif}, "Times New Roman", serif',
                "body_css": sans_css}
    # sans house style — title and body share the sans face.
    return {"title": sans, "body": sans,
            "title_css": sans_css, "body_css": sans_css}
