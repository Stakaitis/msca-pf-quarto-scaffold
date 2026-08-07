#!/usr/bin/env python3
"""gantt.py — generate interactive + static Gantt charts from one task list.

INPUT  : CSV, YAML, or JSON (auto-detected by suffix)
OUTPUT : HTML (interactive) + PNG/PDF/SVG (static), all from one Plotly figure.

Task schema (yaml/json):
    tasks:
      - name: "Setup"            # required
        start: 2026-01-06        # required
        end:   2026-01-24        # required
        category: "Planning"     # optional — drives bar color
        progress: 80             # optional — 0-100
        owner: "alice"           # optional — shown in hover
        milestone: false         # optional — true ⇒ diamond marker, no bar
        dependencies: ["Spec"]   # optional — drawn as arrows when --deps

CSV: same column names, one task per row.

Scales to thousands of tasks: the interactive HTML grows freely (scrollable),
while static raster export is clamped to a sane pixel ceiling (with a warning)
so you never accidentally emit a 28000px PNG.

Slide decks (e.g. Lab_template): export a self-contained dark figure with
  --theme black --embed-plotly inline --formats html -o figures -n my_chart
which writes figures/my_chart.html — drop it in and reference by id. The deck
re-blacks the background + unifies fonts, and any axis/legend label matching a
glossary term gets an automatic hover definition, so keep labels glossary-named.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import yaml

# Shared theming lives one directory up (repo) or alongside (container image).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import lib_plot_themes as themes  # noqa: E402

warnings.filterwarnings("ignore", category=DeprecationWarning, module="plotly")

REQUIRED = ("name", "start", "end")
DEFAULTS = {"category": "Task", "progress": 0, "milestone": False, "owner": "", "phase": ""}

# ── Layout / scalability constants ───────────────────────────────────────────
ROW_PX = 26              # vertical pixels per task row
HEADER_PX = 175          # serif masthead + subtitle + top margin (sized for 1.5x fonts)
FOOTER_PX = 70           # date axis + optional source line (no legend)
MIN_HEIGHT = 400
MAX_STATIC_HEIGHT = 5000  # raster export clamps here (kaleido sanity ceiling)
STATIC_WIDTH = 1400
MIN_BAR_DAYS = 0.5       # any bar narrower than this is widened for visibility
PROGRESS_LABEL_LIMIT = 45  # show in-bar "NN%" text only below this many tasks


def _die(msg: str) -> "None":
    sys.exit(f"gantt: {msg}")


def _warn(msg: str) -> None:
    print(f"gantt: warning: {msg}", file=sys.stderr)


def load_tasks(path: Path) -> pd.DataFrame:
    """Read tasks file, auto-detect format, validate, normalise to a DataFrame.

    Fails loud with an actionable message on the things that otherwise corrupt
    a chart silently: missing file, wrong shape, unparseable dates, end<start.
    """
    if not path.exists():
        _die(f"input file not found: {path}")
    suf = path.suffix.lower()
    meta = {}                                   # optional top-level title/description
    try:
        if suf == ".csv":
            df = pd.read_csv(path)
        elif suf in (".yaml", ".yml", ".json"):
            raw = path.read_text()
            data = yaml.safe_load(raw) if suf != ".json" else json.loads(raw)
            if isinstance(data, dict):
                if "tasks" not in data:
                    _die("YAML/JSON object must have a top-level 'tasks:' list")
                meta = {"title": data.get("title"), "description": data.get("description")}
                data = data["tasks"]
            if not isinstance(data, list) or not data:
                _die("no tasks found in input")
            df = pd.DataFrame(data)
        else:
            _die(f"unsupported extension {suf!r} — use .csv / .yaml / .json")
    except (yaml.YAMLError, json.JSONDecodeError, ValueError) as exc:
        _die(f"could not parse {path.name}: {exc}")

    if df.empty:
        _die("input contains zero tasks")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        _die(f"input missing required columns: {missing}")

    for col, default in DEFAULTS.items():
        if col not in df.columns:
            df[col] = default

    # Dates — coerce, then report (and drop) any row we cannot place on a timeline.
    df["start"] = pd.to_datetime(df["start"], errors="coerce")
    df["end"] = pd.to_datetime(df["end"], errors="coerce")
    bad = df[df["start"].isna() | df["end"].isna()]
    if not bad.empty:
        names = ", ".join(map(str, bad["name"].head(8)))
        _warn(f"dropping {len(bad)} task(s) with unparseable start/end: {names}"
              + (" …" if len(bad) > 8 else ""))
        df = df[~(df["start"].isna() | df["end"].isna())]
    if df.empty:
        _die("no tasks left after dropping rows with invalid dates")

    # end < start is a data error; warn and clamp so the bar is visible, not negative.
    inverted = df["end"] < df["start"]
    if inverted.any():
        names = ", ".join(map(str, df.loc[inverted, "name"].head(8)))
        _warn(f"{int(inverted.sum())} task(s) have end < start; clamping: {names}"
              + (" …" if inverted.sum() > 8 else ""))
        df.loc[inverted, "end"] = df.loc[inverted, "start"]

    # Normalise optional fields so downstream never sees NaN/str surprises.
    df["category"] = (df["category"].fillna("Task").astype(str)
                      .replace({"": "Task", "nan": "Task"}))
    df["progress"] = pd.to_numeric(df["progress"], errors="coerce").fillna(0).clip(0, 100)
    df["owner"] = df["owner"].fillna("").astype(str).replace({"nan": ""})
    # .astype("boolean") first so .fillna runs on a real boolean dtype — avoids
    # the pandas 2.x FutureWarning about silently downcasting object arrays.
    df["milestone"] = df["milestone"].astype("boolean").fillna(False).astype(bool)
    df["phase"] = df["phase"].fillna("").astype(str).replace({"nan": ""}).str.strip()
    df = df.reset_index(drop=True)
    df.attrs["title"] = (meta.get("title") or "").strip()
    df.attrs["description"] = (meta.get("description") or "").strip()
    return df


# ─────────────────────────────────────────────────────────────────
# Visual identity — palette, theme and font all come from lib_plot_themes
# (shared with subway.py). --palette {editorial,okabe-ito}, --theme
# {light,dark,white,black,both}, --font {sans,serif}. Tweak the shared sets in
# lib_plot_themes.py to retune both tools at once.
# ─────────────────────────────────────────────────────────────────
def assign_visual_style(df: pd.DataFrame, theme: str = "light",
                        palette: str = "dual", font: str = "sans",
                        transparent: bool = True) -> dict:
    """Return the global style dict for the chosen theme / palette / font.

    One color per category, deterministic order so same input → same colors.
    transparent=True zeroes the background fills and uses the dual-safe palette,
    so the figure blends onto any backdrop with data colors that read on both.
    """
    style = themes.neutrals(theme, transparent=transparent)
    # Transparent figures force the dual-safe palette: the data colors stay
    # constant (and legible) across the light-ink and dark-ink variants, so only
    # the text/strokes flip between them.
    pal = themes.data_palette("dual" if transparent else palette, theme)
    categories = sorted(df["category"].dropna().unique())
    style["color_map"] = {c: pal[i % len(pal)] for i, c in enumerate(categories)}
    style["wrapped_palette"] = len(categories) > len(pal)
    style["track_height"] = 0.62
    faces = themes.resolve_fonts(font)
    style["title_family"] = faces["title_css"]
    style["font_family"] = faces["body_css"]
    # Sans house style sets the title bold (their convention); the serif
    # masthead reads better at regular weight.
    style["title_bold"] = (font == "sans")
    return style


def _x_dtick(span_days: float) -> str | float:
    """Pick a sparse major x gridline interval — axis furniture stays quiet."""
    if span_days <= 21:
        return 86400000.0 * 3     # 3 days
    if span_days <= 90:
        return 86400000.0 * 14    # fortnightly
    if span_days <= 730:
        return "M2"               # every two months
    return "M3"                   # quarterly


def _wrap(text: str, width: int = 46) -> str:
    """Greedy word-wrap to <br>-separated lines (Plotly annotations don't auto-wrap).
    Honours any explicit newlines the author put in the description."""
    out = []
    for para in text.replace("\r", "").split("\n"):
        cur = ""
        for w in para.split():
            if cur and len(cur) + 1 + len(w) > width:
                out.append(cur); cur = w
            else:
                cur = f"{cur} {w}".strip()
        out.append(cur)
    return "<br>".join(out)


_DAY_NS = 86_400_000_000_000   # one day in nanoseconds (the date axis' native unit)


def _toward(corner, nb, rx, ry):
    """A point stepped from `corner` toward neighbour `nb` by the fillet radius
    (rx along an x-leg, ry along a y-leg) — used to round an orthogonal elbow."""
    cx, cy = corner
    nx, ny = nb
    if abs(nx - cx) >= abs(ny - cy):                 # horizontal leg
        return (cx + min(rx, abs(nx - cx) * 0.5) * (1 if nx > cx else -1), cy)
    return (cx, cy + min(ry, abs(ny - cy) * 0.5) * (1 if ny > cy else -1))   # vertical


def _round_corners(pts, rx, ry, n=6):
    """Round each interior right-angle of an orthogonal polyline with a small
    quadratic-Bézier fillet, so the elbows read as smooth curves while staying
    inside the gutter clearance (ry < the row half-gap)."""
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        (x1, y1) = pts[i]
        a = _toward(pts[i], pts[i - 1], rx, ry)
        b = _toward(pts[i], pts[i + 1], rx, ry)
        out.append(a)
        for j in range(1, n):
            t = j / n; mt = 1.0 - t
            out.append((mt*mt*a[0] + 2*mt*t*x1 + t*t*b[0],
                        mt*mt*a[1] + 2*mt*t*y1 + t*t*b[1]))
        out.append(b)
    out.append(pts[-1])
    return out


def _dep_route(xa, ya, xb, yb, obstacles, app, half=0.34):
    """Orthogonal waypoints from a source block's right edge (xa,ya) to a target
    block's left edge (xb,yb). Horizontal travel rides HALF-INTEGER row gutters
    (always free of the row-centred bars); the single vertical descent is placed
    in a column proven clear of the *intermediate* rows' bars — so the connector
    lives entirely in the non-occupied grey area. x in ns-since-epoch, y in rows."""
    d = 1.0 if yb >= ya else -1.0
    g_src, g_tgt = ya + 0.5 * d, yb - 0.5 * d          # gutters beside src / tgt
    lo, hi = (g_src, g_tgt) if g_src <= g_tgt else (g_tgt, g_src)

    def clear(xc):                                     # column free of crossed bars?
        for bx0, bx1, by in obstacles:
            if by + half >= lo and by - half <= hi and bx0 <= xc <= bx1:
                return False
        return True

    if abs(yb - ya) < 1.5:                             # adjacent rows: no descent
        xc = 0.5 * (xa + xb)
    else:
        # Search outward from the target for a column clear of the intermediate
        # rows' bars (a long background bar like "Sample collection" can block the
        # whole span between source and target, so the clear lane may be just past
        # its end — i.e. outside [xa,xb]). Nearest clear column wins.
        step = 2 * _DAY_NS
        xs_all = [v for o in obstacles for v in o[:2]]
        reach = int((max(xs_all) - min(xs_all)) / step) + 4 if xs_all else 200
        cands = [xb - app]
        for i in range(1, reach):
            cands += [xb - i * step, xb + i * step]
        xc = next((c for c in cands if clear(c)), 0.5 * (xa + xb))

    return [(xa, ya), (xa + app, ya), (xa + app, g_src), (xc, g_src),
            (xc, g_tgt), (xb - app, g_tgt), (xb - app, yb), (xb, yb)]


def render(df: pd.DataFrame, title: str, today: pd.Timestamp | None,
           style: dict, group_by_category: bool, draw_deps: bool,
           show_progress: bool, source: str | None = None,
           description: str = "") -> go.Figure:
    """Build the Plotly figure (bars + progress overlay + milestones + today + deps).

    Every task gets a unique integer y-slot, so duplicate task names no longer
    collide on the categorical axis — the name is only a tick label.
    """
    # Phases (optional): a `phase` per task groups rows into labelled swimlanes.
    # When present, rows order by phase (first-appearance order in the file) and
    # keep their AUTHORED order within a phase — the file controls row order, since
    # start-date sorting would scatter a phase's tasks and break the bands.
    has_phases = bool(df["phase"].astype(str).str.len().gt(0).any()) if "phase" in df else False
    bands = []   # (label, y_top, y_bottom, label_y) — one shaded swimlane per phase
    if has_phases:
        rank = {}
        for p in df["phase"].astype(str):
            rank.setdefault(p, len(rank))
        df["_prank"] = df["phase"].astype(str).map(rank)
        df = df.sort_values("_prank", kind="stable").reset_index(drop=True)
        ys, y, GAP = [], 0.0, 1.25            # GAP = header room above each band
        for _, grp in df.groupby("_prank", sort=True):
            label = str(grp["phase"].iloc[0]).strip()
            y += GAP
            label_y, y_top = y - 0.7, y
            for _ in range(len(grp)):
                ys.append(y); y += 1.0
            if label:
                bands.append((label, y_top - 0.5, y - 1.0 + 0.5, label_y))
        df["_y"] = ys
        y_extent = y
    else:
        sort_keys = ["category", "start"] if group_by_category else ["start"]
        df = df.sort_values(sort_keys, kind="stable").reset_index(drop=True)
        df["_y"] = list(range(len(df)))       # one slot per task, top→bottom (axis reversed)
        y_extent = float(len(df))

    n = len(df)
    fig = go.Figure()

    # Phase swimlanes — subtle grey tints read on both white and black backdrops;
    # the label sits in the header gap just above its band (no task row there).
    if has_phases:
        tints = ["rgba(128,128,128,0.05)", "rgba(128,128,128,0.11)"]
        for i, (label, y0, y1, label_y) in enumerate(bands):
            fig.add_hrect(y0=y0, y1=y1, fillcolor=tints[i % 2], opacity=1.0,
                          layer="below", line_width=0)
            fig.add_annotation(xref="paper", x=0.0, xanchor="left",
                               yref="y", y=label_y, yanchor="middle",
                               text=f"<b>{label}</b>", showarrow=False, align="left",
                               font=dict(family=style["title_family"], size=18,
                                         color=style.get("muted", "#888")))

    show_labels = show_progress and n <= PROGRESS_LABEL_LIMIT

    # Display widths: clamp sub-MIN_BAR_DAYS bars up so they stay visible.
    min_ms = MIN_BAR_DAYS * 86400000.0
    raw_ms = (df["end"] - df["start"]).dt.total_seconds() * 1000.0
    disp_ms = raw_ms.clip(lower=min_ms)

    bars = df[~df["milestone"]]
    for cat in sorted(bars["category"].unique()):
        sub = bars[bars["category"] == cat]
        color = style["color_map"].get(cat, "#888")
        widths = disp_ms.loc[sub.index]
        # Hollow scheduled FRAME (full planned span, empty rounded outline) so
        # completion is the only filled ink — half the ink of a translucent wash.
        fig.add_trace(go.Bar(
            x=widths, y=sub["_y"], base=sub["start"], orientation="h",
            name=str(cat),
            marker=dict(color="rgba(0,0,0,0)", cornerradius=5,
                        line=dict(color=color, width=1.2)),
            customdata=list(zip(sub["progress"].astype(int),
                                sub["owner"], sub["name"])),
            hovertemplate=("<b>%{customdata[2]}</b><br>"
                           "Start: %{base|%Y-%m-%d}<br>"
                           "Progress: %{customdata[0]}%<br>"
                           "Owner: %{customdata[1]}<extra></extra>"),
            width=style["track_height"], showlegend=False, zorder=2,
        ))
        if show_progress:
            pct = sub["progress"].to_numpy() / 100.0
            label_txt = [f"{int(p)}%" if (show_labels and p > 0) else ""
                         for p in sub["progress"]]
            fig.add_trace(go.Bar(
                x=widths.to_numpy() * pct, y=sub["_y"], base=sub["start"],
                orientation="h",
                marker=dict(color=color, opacity=1.0, cornerradius=5,
                            line=dict(width=0)),
                width=style["track_height"],
                text=label_txt, textposition="inside", insidetextanchor="middle",
                textfont=dict(color="white", size=15, family=style["font_family"]),
                showlegend=False, hoverinfo="skip", zorder=2,
            ))

    ms = df[df["milestone"]]
    if not ms.empty:
        # Near-black diamonds, self-labelled with their date (no axis lookup).
        fig.add_trace(go.Scatter(
            x=ms["start"], y=ms["_y"], mode="markers+text",
            marker=dict(symbol="diamond", size=17, color=style["milestone"],
                        line=dict(color=style["marker_edge"], width=1.2)),
            text=[f"{d:%b %d}" for d in ms["start"]], textposition="middle right",
            textfont=dict(family=style["font_family"], size=14,
                          color=style["milestone"]),
            name="Milestone", showlegend=False,
            customdata=list(zip(ms["name"])),
            hovertemplate="<b>%{customdata[0]}</b><br>%{x|%Y-%m-%d}<extra></extra>",
            zorder=3,
        ))

    if draw_deps and "dependencies" in df.columns:
        end_xy = {nm: (e, y) for nm, e, y in zip(df["name"], df["end"], df["_y"])}
        start_xy = {nm: (s, y) for nm, s, y in zip(df["name"], df["start"], df["_y"])}
        # Obstacle rects (x0_ns, x1_ns, row) the connectors must route around;
        # zero-width milestone diamonds get a small ±2-day footprint so descents
        # dodge them too.
        obstacles = []
        for s, e, yy, is_ms in zip(df["start"], df["end"], df["_y"], df["milestone"]):
            x0, x1 = float(s.value), float(e.value)
            if x1 - x0 < 4 * _DAY_NS:
                x0, x1 = x0 - 2 * _DAY_NS, x0 + 2 * _DAY_NS
            obstacles.append((x0, x1, yy))
        app, rx, ry = 6 * _DAY_NS, 5 * _DAY_NS, 0.16
        for nm in df["name"]:
            row_deps = df.loc[df["name"] == nm, "dependencies"]
            deps = row_deps.iloc[0] if len(row_deps) else None
            if isinstance(deps, str):
                deps = [d.strip() for d in deps.split(",") if d.strip()]
            elif not isinstance(deps, (list, tuple)):
                deps = []                      # NaN/None when a task has no deps key
            for dep in deps:
                if dep not in end_xy or nm not in start_xy:
                    continue
                (ex, ey), (sx, sy) = end_xy[dep], start_xy[nm]
                # Route end→start through the empty row gutters, then round the
                # right-angles into smooth curves. Drawn under the bars (zorder 1)
                # as a belt-and-braces guard, but the route already avoids every
                # block face, so the line only ever shows in the grey lanes.
                wp = _round_corners(
                    _dep_route(float(ex.value), ey, float(sx.value), sy, obstacles, app),
                    rx, ry)
                fig.add_trace(go.Scatter(
                    x=[pd.Timestamp(int(round(x))) for x, _ in wp], y=[y for _, y in wp],
                    mode="lines", line=dict(color="#9A9A9A", width=2.6, shape="spline"),
                    opacity=0.7, hoverinfo="skip", showlegend=False, zorder=1))
                # arrowhead at the target start (the route arrives horizontally)
                fig.add_annotation(x=sx, y=sy, ax=sx - pd.Timedelta(days=6), ay=sy,
                                   xref="x", yref="y", axref="x", ayref="y",
                                   arrowhead=2, arrowsize=1.2, arrowwidth=2.6,
                                   arrowcolor="#9A9A9A", opacity=0.7, showarrow=True)

    if today is not None:
        fig.add_vline(x=today, line_width=1.5, line_dash="dash",
                      line_color=style["today"])
        # Label as a SEPARATE annotation, not add_vline's annotation_text: in
        # Plotly 6.7 the vline-annotation path computes sum(x) over datetime
        # coordinates, which pandas 2.x rejects (TypeError on int+Timestamp). A
        # point annotation positions directly at x and sidesteps that.
        fig.add_annotation(x=today, yref="paper", y=0.0, yanchor="bottom",
                           xanchor="left", text="Today", showarrow=False,
                           font=dict(family=style["font_family"], size=16,
                                     color=style["today"]))

    span_days = max(1.0, (df["end"].max() - df["start"].min()).total_seconds() / 86400.0)
    span_txt = f"{df['start'].min():%b %d, %Y} – {df['end'].max():%b %d, %Y}"
    subtitle = f"{n} task{'s' if n != 1 else ''} · {span_txt}"
    if style["wrapped_palette"]:
        subtitle += " · ⚠ colors recycle (>10 categories)"

    # Fold category into the y-tick (color already encodes it) and drop the
    # legend — direct row labels beat a swatch key. Two-line only when sparse.
    two_line = n <= 60
    tick_text = []
    for _, r in df.iterrows():
        if r["milestone"] or not two_line:
            tick_text.append(str(r["name"]))
        else:
            tick_text.append(
                f"{r['name']}<br><span style='font-size:14px;"
                f"color:{style['faint']}'>{r['category']}</span>")

    # Two-line tick labels (name + category) need more vertical room per row.
    row_px = 50 if two_line else 32
    bottom_margin = 80 if source else 44
    content_h = max(MIN_HEIGHT, row_px * y_extent + HEADER_PX + FOOTER_PX)
    title_html = f"<b>{title}</b>" if style.get("title_bold") else title
    fig.update_layout(
        title=dict(text=f"{title_html}<br><span style='font-size:20px;"
                        f"color:{style['muted']};font-family:{style['font_family']}'>"
                        f"{subtitle}</span>",
                   x=0.0, xanchor="left", pad=dict(l=28, t=8),
                   font=dict(family=style["title_family"], size=40,
                             color=style["title_ink"])),
        xaxis=dict(type="date", showgrid=True, gridcolor=style["grid"],
                   griddash="dot", dtick=_x_dtick(span_days), ticks="",
                   showline=True, linecolor=style["baseline"], linewidth=1,
                   zeroline=False,
                   tickfont=dict(family=style["font_family"], size=16,
                                 color=style["axis_tick"]),
                   showspikes=True, spikemode="across+marker", spikesnap="cursor",
                   spikecolor=style["today"], spikethickness=1,
                   spikedash="dot", title=""),
        yaxis=dict(autorange="reversed", showgrid=False, showline=False, title="",
                   tickmode="array", tickvals=df["_y"], ticktext=tick_text,
                   tickfont=dict(family=style["font_family"],
                                 size=16 if n <= 60 else 14, color=style["ink"])),
        plot_bgcolor=style["plot_bg"], paper_bgcolor=style["paper"],
        margin=dict(l=205, r=110, t=HEADER_PX, b=bottom_margin),
        height=content_h,
        font=dict(family=style["font_family"], size=19, color=style["ink"]),
        hovermode="y unified",
        hoverlabel=dict(bgcolor=style["hover_bg"], bordercolor=style["baseline"],
                        font=dict(family=style["font_family"], size=19,
                                  color=style["ink"]), align="left"),
        barmode="overlay", bargap=0.34, showlegend=False,
    )
    if source:
        # yshift in PIXELS keeps the credit a fixed gap below the date axis
        # regardless of chart height (paper-fraction y would drift with rows).
        # Named so the HTML rangeslider path can drop it (the slider owns that band).
        fig.add_annotation(name="source-credit",
                           xref="paper", yref="paper", x=0.0, y=0,
                           xanchor="left", yanchor="top", yshift=-52, showarrow=False,
                           text=f"{source} · Generated {pd.Timestamp.today():%Y-%m-%d}",
                           font=dict(family=style["font_family"], size=16,
                                     color=style["faint"]))
    if description:
        # Floating note box in the top-right corner (sits over the empty late-date
        # region of the early rows). Solid panel bg so it reads over any bars.
        fig.add_annotation(name="description",
                           xref="paper", yref="paper", x=1.0, y=1.0,
                           xanchor="right", yanchor="top", showarrow=False,
                           text=_wrap(description, 48), align="left",
                           font=dict(family=style["font_family"], size=16,
                                     color=style["ink"]),
                           bgcolor=style["hover_bg"], bordercolor=style["baseline"],
                           borderwidth=1, borderpad=12, opacity=0.97)
    return fig


def _rangeslider_xaxis(style: dict) -> dict:
    """Theme-styled overview slider + quick framing buttons (HTML only)."""
    return dict(
        rangeslider=dict(visible=True, thickness=0.06, bgcolor=style["slider_bg"],
                         bordercolor=style["slider_border"]),
        rangeselector=dict(x=1, xanchor="right", y=1.06, bgcolor=style["slider_bg"],
                           activecolor=style["today"],
                           font=dict(family=style["font_family"], size=16,
                                     color=style["ink"]),
                           buttons=[dict(step="all", label="All")]),
    )


RASTER_FORMATS = {"png", "jpg", "jpeg"}
VECTOR_FORMATS = {"pdf", "svg"}  # resolution-independent — never pixel-clamped


def write_outputs(fig: go.Figure, out_dir: Path, stem: str, formats: set[str],
                  *, style: dict | None = None, add_rangeslider: bool = False,
                  embed_plotly: str = "cdn"):
    out_dir.mkdir(parents=True, exist_ok=True)
    # 'inline' bundles plotly.js into the HTML (self-contained, works OFFLINE —
    # e.g. dropped into a slide deck served locally); 'cdn' keeps files tiny but
    # needs internet at view time.
    plotlyjs = True if embed_plotly == "inline" else "cdn"
    logical_h = int(fig.layout.height)
    # Raster export bounds total pixels (drops scale as the figure grows tall);
    # vector export (PDF/SVG) keeps the full height at scale 1 — it scales freely.
    raster_h = min(logical_h, MAX_STATIC_HEIGHT)
    raster_scale = 2 if raster_h <= 2400 else (1.5 if raster_h <= 3600 else 1)
    if logical_h > MAX_STATIC_HEIGHT and (formats & RASTER_FORMATS):
        _warn(f"{logical_h}px chart clamped to {MAX_STATIC_HEIGHT}px for RASTER export "
              "(rows compressed). PDF/SVG keep full resolution; HTML stays interactive.")
    html_config = {
        "displaylogo": False, "responsive": True, "displayModeBar": "hover",
        "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d",
                                   "zoomIn2d", "zoomOut2d"],
        "modeBarButtonsToAdd": ["toggleSpikelines"],
        "toImageButtonOptions": {"format": "png", "filename": stem, "scale": 2},
        "scrollZoom": True, "doubleClick": "reset",
    }
    for fmt in sorted(formats):
        path = out_dir / f"{stem}.{fmt}"
        if fmt == "html":
            # Always a copy (the original `fig` is reused for the raster/vector
            # exports below). The rangeslider would bake into a static export, so
            # it's added only here — never for PNG/PDF/SVG.
            f = go.Figure(fig)
            if add_rangeslider and style is not None:
                f.update_xaxes(**_rangeslider_xaxis(style))
                f.layout.annotations = tuple(
                    a for a in f.layout.annotations if a.name != "source-credit")
            # Fill the whole browser window by default: autosize (drop the fixed
            # height/width) + a viewport-sized container + no page margins. Stays
            # responsive (config has responsive:True), so it tracks window resizes.
            f.update_layout(autosize=True, width=None, height=None)
            doc = f.to_html(include_plotlyjs=plotlyjs, config=html_config,
                            full_html=True, default_width="100%", default_height="100vh")
            doc = doc.replace(
                "<head>",
                "<head><style>html,body{margin:0;padding:0;height:100%;overflow:hidden}"
                ".plotly-graph-div{width:100vw!important;height:100vh!important}</style>", 1)
            path.write_text(doc, encoding="utf-8")
        elif fmt in VECTOR_FORMATS:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fig.write_image(path, scale=1, width=STATIC_WIDTH, height=logical_h)
        elif fmt in RASTER_FORMATS:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fig.write_image(path, scale=raster_scale, width=STATIC_WIDTH,
                                height=raster_h)
        else:
            print(f"Skipping unknown format: {fmt}", file=sys.stderr)
            continue
        print(f"Wrote {path}")


def main():
    p = argparse.ArgumentParser(
        description="Generate interactive + static Gantt charts from a task list.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", type=Path, help="Tasks file (.csv / .yaml / .json)")
    p.add_argument("-o", "--output-dir", type=Path, default=Path("."),
                   help="Where to write outputs.")
    p.add_argument("-n", "--name", default="gantt", help="Output filename stem.")
    p.add_argument("-t", "--title", default="Project Gantt", help="Chart title.")
    p.add_argument("--today", default="auto",
                   help="'auto', 'none', or YYYY-MM-DD for the today marker.")
    p.add_argument("--formats", default="html,png,pdf",
                   help="Comma-separated subset of: html, png, pdf, svg "
                        "(pdf/svg are vector; png is raster; html is interactive).")
    p.add_argument("--embed-plotly", default="cdn", choices=["cdn", "inline"],
                   dest="embed_plotly",
                   help="'cdn' (tiny HTML, needs internet) or 'inline' "
                        "(self-contained, works offline — for slide decks).")
    p.add_argument("--theme", default="both",
                   choices=["light", "dark", "white", "black", "both"],
                   help="Ink target. light/white = dark ink (for light backgrounds); "
                        "dark/black = light ink (for dark). DEFAULT 'both' emits a "
                        "_white and a _black copy so you have one for any backdrop.")
    p.add_argument("--palette", default="dual",
                   choices=["dual", "editorial", "okabe-ito"],
                   help="Category colors. DEFAULT 'dual' reads on both light and dark; "
                        "'okabe-ito' is colourblind-safe; 'editorial' is the warm house "
                        "set (editorial/okabe-ito flip per theme — suit --solid only).")
    p.add_argument("--solid", action="store_true",
                   help="Opt out of the transparent default: bake a solid white/black "
                        "background (for a standalone figure with no backdrop).")
    p.add_argument("--font", default="sans", choices=["sans", "serif"],
                   help="Typography. 'sans' = Arial/Helvetica house style; "
                        "'serif' = Georgia masthead + sans body.")
    p.add_argument("--group-by", default="none", choices=["category", "none"],
                   help="'none' = chronological cascade (default); "
                        "'category' = group rows by category, then by start.")
    p.add_argument("--source", default=None,
                   help="Optional credit/source line in the footer (e.g. team name).")
    p.add_argument("--description", default=None,
                   help="Short project blurb shown in a top-right box (overrides a "
                        "'description:' field in the YAML/JSON).")
    p.add_argument("--deps", action="store_true",
                   help="Draw dependency arrows (off by default — can crowd).")
    p.add_argument("--from", dest="date_from", default=None,
                   help="Drop tasks ending before this date (YYYY-MM-DD).")
    p.add_argument("--to", dest="date_to", default=None,
                   help="Drop tasks starting after this date (YYYY-MM-DD).")
    p.add_argument("--max-tasks", type=int, default=None,
                   help="Cap the number of tasks (earliest-start first) for static export.")
    p.add_argument("--no-progress", action="store_true",
                   help="Disable the progress overlay (just show scheduled bars).")
    args = p.parse_args()

    df = load_tasks(args.input)
    # Title/description: CLI wins, else the YAML/JSON top-level field (captured on
    # df.attrs before the filtering below can drop them).
    title = args.title if args.title != "Project Gantt" else (df.attrs.get("title") or args.title)
    description = args.description if args.description is not None else df.attrs.get("description", "")

    def _parse_date(flag, val):
        try:
            return pd.to_datetime(val)
        except (ValueError, TypeError):
            _die(f"{flag} is not a valid date: {val!r}")

    if args.date_from:
        df = df[df["end"] >= _parse_date("--from", args.date_from)].reset_index(drop=True)
    if args.date_to:
        df = df[df["start"] <= _parse_date("--to", args.date_to)].reset_index(drop=True)
    if df.empty:
        _die("no tasks remain after --from/--to filter")

    if args.max_tasks is not None and len(df) > args.max_tasks:
        _warn(f"capping {len(df)} tasks to {args.max_tasks} (earliest-start first)")
        df = df.sort_values("start", kind="stable").head(args.max_tasks).reset_index(drop=True)

    if args.today == "none":
        today = None
    elif args.today == "auto":
        today = pd.Timestamp.today().normalize()
    else:
        today = _parse_date("--today", args.today)

    formats = {f.strip().lower() for f in args.formats.split(",") if f.strip()}
    span_days = (df["end"].max() - df["start"].min()).days
    add_rangeslider = span_days > 60 and "html" in formats

    # 'both' renders white + black in one run; files take a _<bg> suffix so the
    # pair never collides (matches the Riboseq _white/_black convention).
    bgs = ["white", "black"] if args.theme == "both" else [args.theme]
    for bg in bgs:
        style = assign_visual_style(df, theme=bg, palette=args.palette,
                                    font=args.font, transparent=not args.solid)
        fig = render(df, title, today, style,
                     group_by_category=(args.group_by == "category"),
                     draw_deps=args.deps,
                     show_progress=not args.no_progress,
                     source=args.source, description=description)
        stem = f"{args.name}_{themes.bg_name(bg)}" if len(bgs) > 1 else args.name
        write_outputs(fig, args.output_dir, stem, formats,
                      style=style, add_rangeslider=add_rangeslider,
                      embed_plotly=args.embed_plotly)


if __name__ == "__main__":
    main()
