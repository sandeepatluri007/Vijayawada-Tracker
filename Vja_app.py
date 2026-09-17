"""
Smart Meter Field Tracker
=========================
Backend : streamlit-gsheets-connection  (Google Sheets)
Theme   : Clean White & Light Greys (Field-Optimized)
Security: PIN Protected (stays unlocked until the browser tab is closed)

requirements.txt must include: streamlit, streamlit-gsheets-connection, pandas,
openpyxl, matplotlib (used for the "Download as Image" table exports, the
Hourly Count heatmap view, and the Map's PNG snapshot export). pydeck powers
the Map tab's pin map — it ships bundled with streamlit, so it normally does
not need to be listed separately; add it explicitly only if the Map tab
errors with a missing-module message.

Google Sheet worksheets required (create these tabs in your Sheet, header row only —
the app creates and appends data automatically):
  Installations       - date, tech_name, installer_id, location, qty_1ph, qty_3ph
  Inventory            - date, type, qty, mrn, make
  Technicians           - name, phone, aadhar, is_active, login_id
  Locations             - location_name
  UploadedInstallLog    - key, date, time, installer_id, tech_name, location, meter_type,
                           sno, old_meter_no, new_meter_no, lat, long, source
  AnalyticsRaw          - key, date, time, installer_id, hour, location, meter_type,
                           sno, old_meter_no, new_meter_no, lat, long
  MapRecords            - key, date, time, installer_id, tech_name, location, sno,
                           old_meter_no, new_meter_no, lat, long
                           (Map tab ONLY — never touches Installations/inventory. Populated
                           by a one-way mirror from Installs-tab uploads + Analytics pushes,
                           plus the Map tab's own independent Legacy Data upload.)
"""

import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import date, datetime, time as dtime, timedelta
import urllib.parse
import math
import time
import io
import hashlib
import openpyxl
import matplotlib
matplotlib.use("Agg")
import pydeck as pdk
from fpdf import FPDF

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Field Meter Tracker",
    page_icon="⚡",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── Constants ─────────────────────────────────────────────────────────────────
PIN_CODE = "1323"

# ── 1PH Incentive Billing (from '1Ph Incentive Tier Calculator.xlsx') ───────
# Progressive slab structure, like a tax bracket: each slab's rate applies
# only to the installs that fall within that band, not the whole total.
# Scoped to 1PH only — the uploaded calculator doesn't cover 3PH, so the
# Dashboard tile is explicitly labeled "1PH Billing" rather than guessing at
# a 3PH rate. Update these constants (and INCENTIVE_TIER_SLABS_1PH) if the
# approved rates change.
INCENTIVE_UNIT_RATE_1PH = 165.0     # Rs./install — proposed unit rate
INCENTIVE_FLAT_ADDON_1PH = 15.0     # Rs./install — flat add-on
INCENTIVE_TIER_SLABS_1PH = [
    # (From, To, Incentive Rate Rs./install)
    (1, 1000, 0),
    (1001, 1500, 20),
    (1501, 2500, 30),
    (2501, 3500, 45),
    (3501, 9_999_999, 60),
]


def calculate_1ph_incentive_billing(total_installs: int) -> dict:
    """Replicates the '1Ph Incentive Tier Calculator' workbook's formula
    exactly: Installs_in_slab = MAX(0, MIN(total,To) - MIN(total,From-1)),
    Slab Incentive = Installs_in_slab x Rate, summed across all slabs.
    Total Monthly Cost = Base Cost + Tiered Slab Incentive + Flat Add-on."""
    if total_installs <= 0:
        return {"base_cost": 0.0, "tier_incentive": 0.0, "flat_addon": 0.0, "total_cost": 0.0, "blended_per_install": 0.0, "slabs": []}
    slab_breakdown = []
    tier_incentive = 0.0
    for lo, hi, rate in INCENTIVE_TIER_SLABS_1PH:
        installs_in_slab = max(0, min(total_installs, hi) - min(total_installs, lo - 1))
        slab_amount = installs_in_slab * rate
        tier_incentive += slab_amount
        slab_breakdown.append({"From": lo, "To": hi if hi < 9_999_999 else "∞", "Rate (Rs.)": rate, "Installs": installs_in_slab, "Amount (Rs.)": slab_amount})
    base_cost = total_installs * INCENTIVE_UNIT_RATE_1PH
    flat_addon = total_installs * INCENTIVE_FLAT_ADDON_1PH
    total_cost = base_cost + tier_incentive + flat_addon
    return {
        "base_cost": base_cost, "tier_incentive": tier_incentive, "flat_addon": flat_addon,
        "total_cost": total_cost, "blended_per_install": total_cost / total_installs,
        "slabs": slab_breakdown,
    }
# A stable per-PIN token, remembered in the browser (localStorage) after a
# successful login, so Streamlit Community Cloud's app-sleep / session-reset
# behavior doesn't force a fresh PIN entry on a device that already unlocked
# it — this trades a little security for not re-typing the PIN constantly.
# Change PIN_CODE any time to invalidate every remembered browser at once.
REMEMBER_TOKEN = hashlib.sha256((PIN_CODE + "vja-remember-v1").encode()).hexdigest()[:20]
READ_TTL = 90  # seconds — cuts down on redundant Sheets reads (raised from 30s: the app now
# reads 7 worksheets across multiple tabs/tools, and a low TTL meant far more real Google
# Sheets API calls than needed, which is the main driver of "connection drop" messages)
HALF_DAY_CUTOFF = "13:30:00"  # H1 = first install .. 13:30, H2 = 13:30 .. last install
FORECAST_DAY_END = "18:00:00"  # assumed end-of-workday for the forecasted-total projection

# ── Conditional formatting thresholds ────────────────────────────────────────
# Mirrors the colour rules used in the LoginID_Summary sheet of the MDM export.
# Tune these if your team size / daily targets differ.
CF_GREEN_BG, CF_GREEN_FONT = "#C6EFCE", "#006100"
CF_YELLOW_BG, CF_YELLOW_FONT = "#FFEB9C", "#9C5700"
CF_ORANGE_BG, CF_ORANGE_FONT = "#FFD9B3", "#9C5000"
CF_RED_BG, CF_RED_FONT = "#FFC7CE", "#9C0006"

# Per installer × hour cell (e.g. B3:L13 in the source sheet): <2 red, =2 yellow, >2 green
HOURLY_CELL_THRESHOLD = 2
# Per-installer daily Total column (M3:M13 / Q16:Q26): <10 red, 10-15 neutral, 15-20 yellow, >20 green
INSTALLER_TOTAL_RED_MAX, INSTALLER_TOTAL_YELLOW_MIN, INSTALLER_TOTAL_YELLOW_MAX = 10, 15, 20
# Bottom TOTAL row, per-hour aggregate (B14:L14 / U17:U27): same 4-tier scheme
HOURLY_TOTAL_RED_MAX, HOURLY_TOTAL_YELLOW_MIN, HOURLY_TOTAL_YELLOW_MAX = 10, 15, 20
# Grand total for the day (M14): <150 red, 150-200 yellow, >200 green
GRAND_TOTAL_RED_MAX, GRAND_TOTAL_YELLOW_MAX = 150, 200
# Avg install time in minutes (V32:V42): <20 green (fast), 20-30 yellow, >30 red (slow)
AVG_TIME_GREEN_MAX, AVG_TIME_YELLOW_MAX = 20, 30


def tier_colors(v, red_max, yellow_min, yellow_max):
    """4-tier: <red_max red · red_max-yellow_min orange · yellow_min-yellow_max yellow · >yellow_max green.
    Returns a (bg_hex, font_hex) tuple, or (None, None) if v isn't numeric.
    Shared by the on-screen CSS styling and the exported-image renderer so both
    always show identical colours."""
    try:
        v = float(v)
    except Exception:
        return (None, None)
    if v < red_max:
        return (CF_RED_BG, CF_RED_FONT)
    if v < yellow_min:
        return (CF_ORANGE_BG, CF_ORANGE_FONT)
    if v <= yellow_max:
        return (CF_YELLOW_BG, CF_YELLOW_FONT)
    return (CF_GREEN_BG, CF_GREEN_FONT)


def tier_style(v, red_max, yellow_min, yellow_max):
    bg, fg = tier_colors(v, red_max, yellow_min, yellow_max)
    return f"background-color:{bg};color:{fg}" if bg else ""


def _style_map(styler, func, subset=None):
    """pandas renamed Styler.applymap -> Styler.map (2.1+) and later removed
    applymap entirely, while older pandas doesn't have .map on Styler yet.
    Try the modern name first, fall back to the old one, so this works across
    whatever pandas version Streamlit Cloud happens to have installed."""
    try:
        return styler.map(func, subset=subset) if subset is not None else styler.map(func)
    except AttributeError:
        return styler.applymap(func, subset=subset) if subset is not None else styler.applymap(func)


def cell_colors_3tier(v, mid):
    """3-tier for a single count cell: <mid red · =mid yellow · >mid green."""
    try:
        v = float(v)
    except Exception:
        return (None, None)
    if v < mid:
        return (CF_RED_BG, CF_RED_FONT)
    if v == mid:
        return (CF_YELLOW_BG, CF_YELLOW_FONT)
    return (CF_GREEN_BG, CF_GREEN_FONT)


def cell_style_3tier(v, mid):
    bg, fg = cell_colors_3tier(v, mid)
    return f"background-color:{bg};color:{fg}" if bg else ""


def avg_time_colors(v):
    """Lower avg install time is better: <20 green · 20-30 yellow · >30 red."""
    try:
        v = float(v)
    except Exception:
        return (None, None)
    if v <= 0:
        return (None, None)
    if v < AVG_TIME_GREEN_MAX:
        return (CF_GREEN_BG, CF_GREEN_FONT)
    if v <= AVG_TIME_YELLOW_MAX:
        return (CF_YELLOW_BG, CF_YELLOW_FONT)
    return (CF_RED_BG, CF_RED_FONT)


def avg_time_style(v):
    bg, fg = avg_time_colors(v)
    return f"background-color:{bg};color:{fg}" if bg else ""


def style_hourly_table(df: pd.DataFrame, hour_cols):
    """Applies the LoginID_Summary-style colouring: per-cell 3-tier for each
    installer's hour buckets, 4-tier for the Total column, and a matching
    4-tier scheme for the bottom aggregate TOTAL row."""
    def styler(data):
        css = pd.DataFrame("", index=data.index, columns=data.columns)
        for i in data.index:
            is_total_row = str(data.loc[i, "Installer"]).strip().upper() == "TOTAL"
            for h in hour_cols:
                if is_total_row:
                    css.loc[i, h] = tier_style(data.loc[i, h], HOURLY_TOTAL_RED_MAX, HOURLY_TOTAL_YELLOW_MIN, HOURLY_TOTAL_YELLOW_MAX)
                else:
                    css.loc[i, h] = cell_style_3tier(data.loc[i, h], HOURLY_CELL_THRESHOLD)
            if "Total" in data.columns:
                css.loc[i, "Total"] = tier_style(data.loc[i, "Total"], INSTALLER_TOTAL_RED_MAX, INSTALLER_TOTAL_YELLOW_MIN, INSTALLER_TOTAL_YELLOW_MAX)
        return css
    return df.style.apply(styler, axis=None)


# ── Export-as-image helpers (Dashboard + Analytics "Download as Image") ─────
def build_hourly_color_grid(df: pd.DataFrame, hour_cols):
    """Per-cell (bg, font) grid matching style_hourly_table's on-screen colours,
    for rendering the same table as a PNG."""
    grid = []
    for i in range(len(df)):
        is_total_row = str(df.iloc[i]["Installer"]).strip().upper() == "TOTAL"
        row_colors = []
        for col in df.columns:
            if col == "Installer":
                row_colors.append((None, None))
            elif col in hour_cols:
                v = df.iloc[i][col]
                row_colors.append(
                    tier_colors(v, HOURLY_TOTAL_RED_MAX, HOURLY_TOTAL_YELLOW_MIN, HOURLY_TOTAL_YELLOW_MAX)
                    if is_total_row else cell_colors_3tier(v, HOURLY_CELL_THRESHOLD)
                )
            elif col == "Total":
                row_colors.append(tier_colors(df.iloc[i][col], INSTALLER_TOTAL_RED_MAX, INSTALLER_TOTAL_YELLOW_MIN, INSTALLER_TOTAL_YELLOW_MAX))
            else:
                row_colors.append((None, None))
        grid.append(row_colors)
    return grid


def build_single_col_color_grid(df: pd.DataFrame, col_name: str, color_func):
    """(bg, font) grid with colour only on one column — used for the Total
    column of the Technician Breakdown table and the avg-time table."""
    grid = []
    for i in range(len(df)):
        row_colors = []
        for col in df.columns:
            row_colors.append(color_func(df.iloc[i][col]) if col == col_name else (None, None))
        grid.append(row_colors)
    return grid


def dataframe_to_png_bytes(df: pd.DataFrame, color_grid=None, title: str = None) -> bytes:
    """Renders a DataFrame (optionally with a matching (bg,font) colour grid)
    as a PNG, so tables can be shared as an image (e.g. over WhatsApp).
    "Fit to screen": the canvas is capped at MAX_FIG_W x MAX_FIG_H instead of
    growing without bound for large tables — beyond that cap, font size and
    row height shrink to still fit everything on one canvas, so the image
    doesn't need pinch-zooming or scrolling to view on a phone."""
    import matplotlib.pyplot as plt

    MAX_FIG_W, MAX_FIG_H = 9.0, 13.0

    n_rows, n_cols = df.shape
    title_lines = title.count("\n") + 1 if title else 0
    raw_w = max(6.0, n_cols * 1.35)
    raw_h = max(2.0, (n_rows + 2) * 0.42) + title_lines * 0.35

    fig_w = min(raw_w, MAX_FIG_W)
    fig_h = min(raw_h, MAX_FIG_H)
    shrink = min(fig_w / raw_w, fig_h / raw_h, 1.0)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.axis("off")
    if title:
        ax.set_title(title, fontsize=max(9, round(13 * shrink)), fontweight="bold", loc="left", pad=14)

    cell_text = df.astype(str).values
    tbl = ax.table(cellText=cell_text, colLabels=list(df.columns), cellLoc="center", loc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(max(6, round(10 * shrink)))
    tbl.scale(1, max(1.1, 1.7 * shrink))
    tbl.auto_set_column_width(col=list(range(n_cols)))

    for j in range(n_cols):
        header_cell = tbl[0, j]
        header_cell.set_facecolor("#10151F")
        header_cell.set_text_props(color="white", fontweight="bold")

    for i in range(n_rows):
        for j in range(n_cols):
            cell = tbl[i + 1, j]
            bg, fg = (None, None)
            if color_grid is not None:
                bg, fg = color_grid[i][j]
            cell.set_facecolor(bg if bg else ("#FFFFFF" if i % 2 == 0 else "#F6F7F9"))
            if fg:
                cell.set_text_props(color=fg, fontweight="bold")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def download_image_button(df: pd.DataFrame, file_name: str, key: str, color_grid=None, title: str = None, label: str = "📷 Download as Image"):
    """Download-as-Image button for the given table.

    Rendering a table to PNG via matplotlib costs ~0.3s. Streamlit re-runs the
    WHOLE script (every tab body, not just the visible one) on every widget
    interaction, so eagerly building these made each click pay for every
    export image in the app whether or not anyone wanted one. The PNG is now
    built only after the user asks for it."""
    if df.empty:
        return
    want_key = f"{key}__prepare"
    if st.session_state.get(want_key):
        png_bytes = dataframe_to_png_bytes(df, color_grid=color_grid, title=title)
        st.download_button(label, data=png_bytes, file_name=file_name, mime="image/png", use_container_width=True, key=key)
    else:
        if st.button(label, use_container_width=True, key=f"{key}__btn"):
            st.session_state[want_key] = True
            st.rerun()


def build_map_snapshot_png(df: pd.DataFrame, title: str) -> bytes:
    """A positional scatter of the filtered pins (Longitude/Latitude, no
    street/satellite basemap tiles — the app has no mapping API key
    configured) saved as a shareable PNG. This is a plot of the pin
    positions, not a screenshot of the interactive tile map above."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    ax.scatter(df["_long"], df["_lat"], s=45, c="#0E9F6E", edgecolors="white", linewidths=0.9, zorder=3)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(title, fontsize=12, fontweight="bold", wrap=True)
    ax.grid(True, linestyle="--", alpha=0.4)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# ── Real-basemap map snapshot (used by the weekly customer report) ──────────
# The interactive Map tab's pydeck view shows real street-map tiles without
# needing an API key (pydeck's default free tile provider). matplotlib can't
# fetch map tiles on its own, so for a static PNG we fetch the same style of
# free XYZ tiles directly (CARTO's "light_all" basemap, no key required) and
# composite the filtered points on top — giving a snapshot that matches what
# you see live on the Map tab, cropped tightly to just those points.
TILE_SIZE = 256
# OpenStreetMap's standard tiles need no API key. (CARTO's basemaps.cartocdn.com
# now stamps an "API key missing" watermark across its tiles, which was showing
# up in generated reports.) OSM's usage policy requires a real User-Agent and
# only permits modest volumes — fine for a handful of report snippets, but
# don't raise TILE_MAX_GRID much or generate reports in bulk.
TILE_URL_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_ATTRIBUTION = "(c) OpenStreetMap contributors"
TILE_MAX_ZOOM = 18
TILE_MAX_GRID = 5  # cap how many tiles wide/tall we'll fetch, to keep requests fast
TILE_MIN_ASPECT = 0.55  # keep snippets from rendering as a squashed letterbox strip


def _lonlat_to_pixel(lon: float, lat: float, zoom: int) -> tuple:
    """Web Mercator: absolute pixel coordinates at a given zoom (256px tiles)."""
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n * TILE_SIZE
    y = (1.0 - math.log(math.tan(lat_rad) + (1 / math.cos(lat_rad))) / math.pi) / 2.0 * n * TILE_SIZE
    return x, y


def build_basemap_snapshot_png(lats, lons, title: str = None, point_labels=None) -> bytes:
    """Fetches real basemap tiles and plots the given lat/lon points on top,
    auto-zoomed and cropped to fit just those points (with a little padding)
    — a static equivalent of what the interactive Map tab shows live. Falls
    back to the plain scatter-only style (build_map_snapshot_png) if tiles
    can't be fetched (e.g. no internet access from wherever this runs)."""
    import requests
    from PIL import Image, ImageDraw, ImageFont

    lats = list(lats)
    lons = list(lons)
    if not lats or not lons:
        raise ValueError("No points to plot")

    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    # Pad the bbox so points near the edge aren't flush against the border;
    # enforce a minimum span so a tight cluster (or a single point) doesn't
    # collapse to a zero-size box.
    lat_span = max(max_lat - min_lat, 0.004)
    lon_span = max(max_lon - min_lon, 0.004)

    # Installs strung along a road produce a very wide, very short bbox, which
    # renders as an unreadable letterbox strip. Widen whichever axis is too
    # thin so the snippet keeps a sensible shape.
    lat_extent = lat_span * math.cos(math.radians((min_lat + max_lat) / 2))  # deg lon are narrower away from equator
    if lat_span > 0 and lon_span > 0:
        aspect = lat_extent / lon_span if lon_span else 1.0
        if aspect < TILE_MIN_ASPECT:
            lat_span = (lon_span * TILE_MIN_ASPECT) / max(math.cos(math.radians((min_lat + max_lat) / 2)), 1e-6)
        elif aspect > 1 / TILE_MIN_ASPECT:
            lon_span = lat_extent / TILE_MIN_ASPECT
        center_lat, center_lon = (min_lat + max_lat) / 2, (min_lon + max_lon) / 2
        min_lat, max_lat = center_lat - lat_span / 2, center_lat + lat_span / 2
        min_lon, max_lon = center_lon - lon_span / 2, center_lon + lon_span / 2

    pad_lat, pad_lon = lat_span * 0.15, lon_span * 0.15
    min_lat, max_lat = min_lat - pad_lat, max_lat + pad_lat
    min_lon, max_lon = min_lon - pad_lon, max_lon + pad_lon

    try:
        # Pick the highest zoom where the padded bbox still fits within
        # TILE_MAX_GRID tiles on each axis.
        zoom = TILE_MAX_ZOOM
        for z in range(TILE_MAX_ZOOM, 0, -1):
            x1, y1 = _lonlat_to_pixel(min_lon, max_lat, z)  # top-left
            x2, y2 = _lonlat_to_pixel(max_lon, min_lat, z)  # bottom-right
            tiles_wide = (x2 - x1) / TILE_SIZE
            tiles_tall = (y2 - y1) / TILE_SIZE
            if tiles_wide <= TILE_MAX_GRID and tiles_tall <= TILE_MAX_GRID:
                zoom = z
                break
        else:
            zoom = 1

        px1, py1 = _lonlat_to_pixel(min_lon, max_lat, zoom)
        px2, py2 = _lonlat_to_pixel(max_lon, min_lat, zoom)

        tile_x1, tile_y1 = int(px1 // TILE_SIZE), int(py1 // TILE_SIZE)
        tile_x2, tile_y2 = int(px2 // TILE_SIZE), int(py2 // TILE_SIZE)

        composite_w = (tile_x2 - tile_x1 + 1) * TILE_SIZE
        composite_h = (tile_y2 - tile_y1 + 1) * TILE_SIZE
        composite = Image.new("RGB", (composite_w, composite_h), "#E7E9EE")

        for tx in range(tile_x1, tile_x2 + 1):
            for ty in range(tile_y1, tile_y2 + 1):
                try:
                    resp = requests.get(TILE_URL_TEMPLATE.format(z=zoom, x=tx, y=ty), timeout=6,
                                         headers={"User-Agent": "SmartMeterFieldTracker/1.0"})
                    if resp.status_code == 200:
                        tile_img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                        composite.paste(tile_img, ((tx - tile_x1) * TILE_SIZE, (ty - tile_y1) * TILE_SIZE))
                except Exception:
                    continue  # leave that tile blank rather than failing the whole snapshot

        # Crop to the exact padded bbox (not the full tile grid).
        origin_x, origin_y = tile_x1 * TILE_SIZE, tile_y1 * TILE_SIZE
        crop_box = (int(px1 - origin_x), int(py1 - origin_y), int(px2 - origin_x), int(py2 - origin_y))
        cropped = composite.crop(crop_box)

        draw = ImageDraw.Draw(cropped)
        for i, (lat, lon) in enumerate(zip(lats, lons)):
            x, y = _lonlat_to_pixel(lon, lat, zoom)
            x, y = x - origin_x - crop_box[0], y - origin_y - crop_box[1]
            r = 6
            draw.ellipse([x - r, y - r, x + r, y + r], fill="#0E9F6E", outline="white", width=2)
            if point_labels and i < len(point_labels) and point_labels[i]:
                draw.text((x + r + 3, y - r), str(point_labels[i]), fill="#10151F")

        # OSM's tile usage policy requires visible attribution.
        try:
            attr_font = ImageFont.load_default(size=11)
        except Exception:
            attr_font = ImageFont.load_default()
        attr_w = draw.textlength(TILE_ATTRIBUTION, font=attr_font) if hasattr(draw, "textlength") else 140
        draw.rectangle([cropped.width - attr_w - 8, cropped.height - 16, cropped.width, cropped.height], fill="white")
        draw.text((cropped.width - attr_w - 4, cropped.height - 14), TILE_ATTRIBUTION, fill="#64748B", font=attr_font)

        if title:
            banner_h = 34
            banner = Image.new("RGB", (cropped.width, cropped.height + banner_h), "white")
            banner.paste(cropped, (0, banner_h))
            d2 = ImageDraw.Draw(banner)
            try:
                font = ImageFont.load_default(size=16)
            except Exception:
                font = ImageFont.load_default()
            d2.text((8, 8), title, fill="#10151F", font=font)
            cropped = banner

        buf = io.BytesIO()
        cropped.save(buf, format="PNG")
        buf.seek(0)
        return buf.getvalue()
    except Exception:
        # Network unavailable or tile fetch failed — fall back to the plain
        # scatter-only style rather than erroring out the whole report.
        fallback_df = pd.DataFrame({"_lat": lats, "_long": lons})
        return build_map_snapshot_png(fallback_df, title or "Install Locations")


def build_kml(df: pd.DataFrame, doc_name: str = "Installed Meters") -> bytes:
    """Standard KML with one Placemark per row (needs _lat/_long numeric
    columns) — openable in Google Earth, Google My Maps, QGIS, or any other
    GIS tool the field team already has."""
    import xml.sax.saxutils as sx

    def esc(v):
        return sx.escape(str(v)) if v is not None else ""

    detail_labels = [
        ("SNO", "sno"), ("Section", "location"), ("Date", "date"), ("Time", "time"),
        ("Installer", "tech_name"), ("Old Meter No", "old_meter_no"), ("New Meter No", "new_meter_no"),
    ]
    placemarks = []
    for _, r in df.iterrows():
        name = str(r.get("sno") or r.get("tech_name") or "Install").strip()
        desc_lines = [f"{label}: {esc(r.get(col))}" for label, col in detail_labels if col in df.columns and str(r.get(col, "")).strip()]
        description = "&#10;".join(desc_lines)
        placemarks.append(
            f"<Placemark><name>{esc(name)}</name><description>{description}</description>"
            f"<Point><coordinates>{r['_long']},{r['_lat']},0</coordinates></Point></Placemark>"
        )

    kml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"<name>{esc(doc_name)}</name>{''.join(placemarks)}"
        "</Document></kml>"
    )
    return kml.encode("utf-8")


def dataframe_height(n_rows: int, row_px: int = 38, header_px: int = 38, max_px: int = 640) -> int:
    """Height (px) that fits every row without Streamlit's internal vertical
    scrollbar, capped at max_px for very long tables (which fall back to the
    normal scrollable view rather than pushing the page too tall)."""
    return min(header_px + row_px * max(n_rows, 1) + 3, max_px)


def render_hourly_heatmap(df: pd.DataFrame, hour_cols, color_grid):
    """Alternative to the wide Hourly Count table: a compact heatmap (installer
    x hour + Total) that scales to the container width instead of needing
    horizontal scrolling for teams with many active hours in a day."""
    import matplotlib.pyplot as plt
    import numpy as np

    cols_to_plot = hour_cols + ["Total"]
    n_rows = len(df)
    fig_w = max(6.0, len(cols_to_plot) * 0.85)
    fig_h = max(2.0, n_rows * 0.5 + 1.2)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    def hex_to_rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    img = np.ones((n_rows, len(cols_to_plot), 3))
    for i in range(n_rows):
        for j, col in enumerate(cols_to_plot):
            col_idx = df.columns.get_loc(col)
            bg, _ = color_grid[i][col_idx]
            img[i, j] = hex_to_rgb(bg) if bg else (1, 1, 1)

    ax.imshow(img, aspect="auto")
    ax.set_xticks(range(len(cols_to_plot)))
    ax.set_xticklabels(cols_to_plot, rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(df["Installer"].tolist(), fontsize=9)
    for i in range(n_rows):
        for j, col in enumerate(cols_to_plot):
            ax.text(j, i, str(df.iloc[i][col]), ha="center", va="center", fontsize=9, fontweight="bold", color="#10151F")
    ax.set_xticks(np.arange(-0.5, len(cols_to_plot), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n_rows, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.5)
    ax.tick_params(which="minor", size=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


def render_colored_metric(label: str, value: int, red_max: int, yellow_max: int):
    """A st.metric look-alike whose background/text colour reflects thresholds
    (mirrors the M14 grand-total cell colouring in the source sheet)."""
    if value < red_max:
        bg, fg = CF_RED_BG, CF_RED_FONT
    elif value <= yellow_max:
        bg, fg = CF_YELLOW_BG, CF_YELLOW_FONT
    else:
        bg, fg = CF_GREEN_BG, CF_GREEN_FONT
    st.markdown(f"""
    <div style="background:{bg};color:{fg};border-radius:14px;padding:16px 14px;
        border:1px solid rgba(0,0,0,0.06);text-align:left;">
        <div style="font-size:.72rem;font-weight:600;text-transform:uppercase;letter-spacing:.4px;opacity:.85;">{label}</div>
        <div style="font-size:1.7rem;font-weight:800;letter-spacing:-.3px;">{value}</div>
    </div>
    """, unsafe_allow_html=True)


# ── CSS – Fintech-Inspired Theme (single accent, segmented tabs) ────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    --accent: #0E9F6E;
    --accent-dark: #0B7A56;
    --accent-soft: #E6F7F0;
    --ink: #10151F;
    --ink-soft: #64748B;
    --bg: #F6F7F9;
    --card-border: #E7E9EE;
}

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: var(--bg); color: var(--ink); }
#MainMenu, footer, header { visibility:hidden; }

.top-banner {
    background: #ffffff;
    border: 1px solid var(--card-border);
    border-radius: 16px;
    padding: 14px 18px;
    display:flex; align-items:center; gap:12px;
    box-shadow: 0 1px 2px rgba(16,21,31,0.04);
}
.top-banner .icon-badge {
    width:40px; height:40px; border-radius:12px; background:var(--accent-soft);
    display:flex; align-items:center; justify-content:center; font-size:1.3rem; flex-shrink:0;
}
.top-banner .t { font-size:1.15rem; font-weight:800; color:var(--ink); letter-spacing:-.2px; margin:0; }
.top-banner .s { font-size:.78rem; color:var(--ink-soft); margin:0; font-weight:500; }

/* Segmented-control style tabs, closer to Groww/Kite bottom-nav feel */
.stTabs [data-baseweb="tab-list"] {
    background:#EEF0F3; border-radius:12px; padding:4px; gap:2px;
    overflow-x:auto; white-space:nowrap;
}
.stTabs [data-baseweb="tab"] {
    border-radius:9px !important; padding:9px 14px !important;
    font-size:.86rem !important; font-weight:600 !important;
    color:var(--ink-soft) !important;
    background:transparent !important; border:none !important;
}
.stTabs [aria-selected="true"] {
    background:var(--ink) !important;
    color:#ffffff !important;
    box-shadow: 0 1px 3px rgba(16,21,31,0.15);
}

[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid var(--card-border); border-radius:14px;
    padding: 16px 14px !important;
    box-shadow: 0 1px 2px rgba(16,21,31,0.03);
}
[data-testid="stMetricLabel"] {
    color:var(--ink-soft) !important; font-size:.72rem !important; font-weight:600 !important;
    text-transform:uppercase; letter-spacing:.4px;
}
[data-testid="stMetricValue"] {
    font-size:1.7rem !important; font-weight:800 !important; color:var(--ink) !important; letter-spacing:-.3px;
}

.sec-hdr {
    font-size:1.02rem; font-weight:700; color:var(--ink);
    display:flex; align-items:center; gap:8px;
    margin: 1.6rem 0 .9rem;
}
.sec-hdr::before { content:""; width:5px; height:16px; background:var(--accent); border-radius:3px; display:inline-block; }
.sub-hdr {
    font-size:.85rem; font-weight:700; color:var(--ink-soft);
    text-transform:uppercase; letter-spacing:.4px;
    margin: 1.1rem 0 .5rem;
}

.stButton>button {
    background:#ffffff !important; color:var(--ink) !important;
    border:1px solid var(--card-border) !important; border-radius:10px !important;
    font-weight:600 !important; font-size:.92rem !important;
    padding:10px 18px !important; width:100% !important;
    transition:all .15s;
    box-shadow: 0 1px 2px rgba(16,21,31,0.02);
}
.stButton>button:hover { border-color:var(--accent) !important; color:var(--accent-dark) !important; }

button[data-testid="baseButton-primary"], .stButton>button[type="primary"] {
    background:var(--accent) !important; color:#ffffff !important; border-color:var(--accent) !important;
}
button[data-testid="baseButton-primary"]:hover, .stButton>button[type="primary"]:hover {
    background:var(--accent-dark) !important; border-color:var(--accent-dark) !important; color:#fff !important;
}

.stSelectbox>div>div, .stNumberInput>div>div>input,
.stTextInput>div>div>input, .stDateInput>div>div>input, .stMultiSelect>div>div {
    background:#ffffff !important; border:1px solid var(--card-border) !important;
    border-radius:10px !important; color:var(--ink) !important; font-size:.9rem !important;
}

.stForm { background:#ffffff !important; border:1px solid var(--card-border) !important;
    border-radius:14px !important; padding:18px !important; }

.stDataFrame { border-radius:12px; border: 1px solid var(--card-border); overflow:hidden; }

.warn-box {
    background:#FFF8E8; border:1px solid #F5D98B; border-radius:11px;
    padding:11px 15px; color:#8A6208; font-size:.85rem; margin-bottom:.8rem; font-weight:500;
}
.info-box {
    background:#F1F5F9; border:1px solid var(--card-border); border-radius:11px;
    padding:11px 15px; color:var(--ink-soft); font-size:.85rem; margin-bottom:.8rem; font-weight:500;
}
.danger-box {
    background:#FEF2F2; border:1px solid #FCA5A5; border-radius:11px;
    padding:11px 15px; color:#991B1B; font-size:.85rem; margin-bottom:.8rem; font-weight:500;
}

.wa-btn {
    display:block; text-align:center; background:#25D366; color:#fff !important;
    padding:13px; border-radius:11px; text-decoration:none; font-weight:700;
    font-size:1rem; letter-spacing:.2px;
    margin-top:1rem; transition: background 0.2s;
    box-shadow: 0 2px 6px rgba(37,211,102,0.25);
}
.wa-btn:hover { background:#1DA851; }
</style>
""", unsafe_allow_html=True)


# ── Top banner & Refresh Button ───────────────────────────────────────────────
head_col1, head_col2 = st.columns([3.5, 1.2])
with head_col1:
    st.markdown("""
    <div class="top-banner">
      <div class="icon-badge">⚡</div>
      <div>
        <p class="t">Meter Tracker</p>
        <p class="s">Vijayawada Field Ops</p>
      </div>
    </div>
    """, unsafe_allow_html=True)
with head_col2:
    st.write("")
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

st.write("")

# ── Authentication / PIN Protection (persists until the app/tab is closed, ──
# and now also survives a Streamlit Community Cloud app-sleep / session reset
# via a "remembered browser" token — see REMEMBER_TOKEN above) ─────────────
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

# 1) Same-run restore: the URL already carries a valid remember token
#    (set right after a previous login on this browser).
if not st.session_state["authenticated"] and st.query_params.get("k") == REMEMBER_TOKEN:
    st.session_state["authenticated"] = True

if not st.session_state["authenticated"]:
    # 2) Cross-visit restore: check this browser's localStorage for a saved
    #    token and, if found, reload the page with it appended to the URL —
    #    covers a fresh app-sleep wake-up, a bookmarked/home-screen open, or
    #    any other visit that dropped the query param.
    st.components.v1.html("""
    <script>
    (function() {
        try {
            const params = new URLSearchParams(window.parent.location.search);
            if (!params.has('k')) {
                const saved = window.parent.localStorage.getItem('vja_remember_token');
                if (saved) {
                    params.set('k', saved);
                    window.parent.location.search = params.toString();
                }
            }
        } catch (e) {}
    })();
    </script>
    """, height=0)

    st.markdown('<div class="sec-hdr">🔒 Supervisor Login</div>', unsafe_allow_html=True)
    with st.form("login_form"):
        st.info("Please enter the daily operations PIN to access the system. This browser will stay unlocked going forward.")
        pin_entry = st.text_input("Enter PIN", type="password")
        login_btn = st.form_submit_button("Unlock Tracker", type="primary")
        if login_btn:
            if pin_entry == PIN_CODE:
                st.session_state["authenticated"] = True
                st.query_params["k"] = REMEMBER_TOKEN
                st.components.v1.html(f"""
                <script>
                try {{ window.parent.localStorage.setItem('vja_remember_token', '{REMEMBER_TOKEN}'); }} catch (e) {{}}
                </script>
                """, height=0)
                st.success("Access Granted!")
                st.rerun()
            else:
                st.error("❌ Incorrect PIN. Access Denied.")
    st.stop()

# ── Cloud Crash Guard: Google Sheets Connection ──────────────────────────────
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("🛑 Database Connection Failed!")
    st.write(f"Error Details: `{e}`")
    st.info("💡 **Fix:** Ensure your `st.secrets` are properly configured and `st-gsheets-connection` is in requirements.txt")
    st.stop()

# ── Helpers ───────────────────────────────────────────────────────────────────
@st.cache_data(ttl=READ_TTL, show_spinner=False)
def _read_worksheet_cached(worksheet: str, _version: int) -> pd.DataFrame:
    """Cached Sheets read. `_version` is bumped by safe_update() so writes
    invalidate the cache immediately; otherwise the same worksheet is fetched
    and string-converted once per TTL window instead of once per call site
    (there are 30+ call sites, and Streamlit re-runs every tab body on each
    interaction, so this was repeated work on every click)."""
    df = conn.read(worksheet=worksheet, ttl=READ_TTL)
    return df.astype(str).fillna("") if not df.empty else pd.DataFrame()


def get_data(worksheet: str, retries: int = 5) -> pd.DataFrame:
    version = st.session_state.get("_sheet_version", 0)
    for attempt in range(retries):
        try:
            return _read_worksheet_cached(worksheet, version).copy()
        except Exception:
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 8))  # 1s, 2s, 4s, 8s — rides out brief rate-limit/network blips
            else:
                st.toast(f"📡 Connection drop loading {worksheet}...", icon="⚠️")
                return pd.DataFrame()


def safe_update(worksheet: str, data: pd.DataFrame, retries: int = 5) -> bool:
    """Write to Sheets with retries so a dropped connection doesn't lose the entry.
    On repeated failure, the data the user entered is NOT cleared — they can just retry."""
    for attempt in range(retries):
        try:
            with st.spinner(f"💾 Saving to {worksheet}..."):
                conn.update(worksheet=worksheet, data=data.astype(str))
            # Bump the read-cache version so the next get_data() refetches,
            # instead of clearing every cached value app-wide.
            st.session_state["_sheet_version"] = st.session_state.get("_sheet_version", 0) + 1
            return True
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(min(2 ** attempt, 8))
            else:
                st.error(f"⚠️ Save failed after several attempts ({e}). Your entries are still in the form — please tap Save again once you have signal.")
                return False
    return False


def safe_int(val, default: int = 0) -> int:
    try:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return default
        return int(float(val))
    except Exception:
        return default


def safe_numeric_col(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(df[col], errors="coerce").fillna(0)


def has_col(df: pd.DataFrame, *cols) -> bool:
    return all(c in df.columns for c in cols)


# ── Excel parsing helpers (used by Installs bulk upload + Analytics upload) ─
def find_header_row(ws, required_headers, max_scan_rows: int = 20):
    """Scan the first N rows for a row containing all required header labels
    (case-insensitive, trimmed). Returns (row_index, {header_label: col_index})
    or (None, None) if not found. Works regardless of whether headers sit on
    row 1 (clean export) or a later row (raw MDM export with a title row)."""
    required_norm = [h.strip().lower() for h in required_headers]
    max_row = min(max_scan_rows, ws.max_row)
    for r in range(1, max_row + 1):
        row_vals = {}
        for c in range(1, ws.max_column + 1):
            v = ws.cell(row=r, column=c).value
            if v is not None and str(v).strip() != "":
                row_vals[str(v).strip().lower()] = c
        if all(h in row_vals for h in required_norm):
            col_map = {orig: row_vals[norm] for orig, norm in zip(required_headers, required_norm)}
            return r, col_map
    return None, None


def find_optional_cols(ws, header_row: int, optional_headers):
    """Given a known header row, look up a handful of extra (non-required)
    column labels on that same row. Returns {label: col_index} only for the
    ones actually present, so callers can treat missing ones as absent."""
    row_vals = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=header_row, column=c).value
        if v is not None and str(v).strip() != "":
            row_vals[str(v).strip().lower()] = c
    return {h: row_vals[h.strip().lower()] for h in optional_headers if h.strip().lower() in row_vals}


# Extra per-record detail columns (present in the same MDM export) that feed
# the Map tab and the meter-number Search box on the Installs tab. All optional
# — files/uploads without them still work, just without these fields filled in.
DETAIL_FIELD_HEADERS = {
    "sno": "Consumer No",
    "old_meter_no": "Old Meter Serial Number",
    "new_meter_no": "New Meter Serial Number",
    "lat": "latitude",
    "long": "longitude",
}

# Column headers required to parse a full installation record (bulk upload,
# legacy upload). Analytics-tab live tracking only strictly needs the first three.
INSTALL_BULK_REQUIRED_HEADERS = ["Installation Date", "Installation Time", "Installer LoginID", "Section", "New Meter Type"]
ANALYTICS_REQUIRED_HEADERS = ["Installation Date", "Installation Time", "Installer LoginID"]

# Only installer/login IDs with this prefix are ever processed or saved —
# applied consistently in the Installs bulk upload, the Legacy Data upload,
# and the Analytics upload, so no non-technician or test rows slip into any
# of the sheets via one path but not another.
INSTALLER_ID_PREFIX = "TL_"


def is_valid_installer_id(raw_installer) -> bool:
    if raw_installer is None:
        return False
    return str(raw_installer).strip().upper().startswith(INSTALLER_ID_PREFIX)


def normalize_coord_val(val):
    """Return a float lat/lon, or None if blank/zero/unparseable."""
    try:
        f = float(str(val).strip())
        if f == 0:
            return None
        return f
    except Exception:
        return None


def extract_detail_fields(ws, row: int, optional_map: dict) -> dict:
    """Pulls SNO / Old Meter No / New Meter No / lat / long for one data row,
    given an optional_map from find_optional_cols(ws, header_row, list(DETAIL_FIELD_HEADERS.values()))."""
    out = {}
    for key, header in DETAIL_FIELD_HEADERS.items():
        col = optional_map.get(header)
        if col is None:
            out[key] = ""
            continue
        val = ws.cell(row=row, column=col).value
        if key in ("lat", "long"):
            coord = normalize_coord_val(val)
            out[key] = coord if coord is not None else ""
        else:
            out[key] = str(val).strip() if val is not None else ""
    return out


def extract_section_code(sno) -> str:
    """The 6th & 7th digit (1-indexed, from the left) of a 13-digit Consumer
    No / SNO is its section code, e.g. 6436126250971 -> '26'.

    Deliberately tolerant about how the SNO arrives: Google Sheets hands back
    numeric cells as '6436126250971.0', sometimes in scientific notation
    ('6.436126250971E+12'), and pasted values can carry a leading apostrophe
    or stray spaces. All of those are the same real service number, so strip
    down to digits first rather than rejecting them as unparseable."""
    s = str(sno).strip()
    if not s:
        return "Unclassified"

    # Scientific notation (e.g. 6.436126250971E+12) -> expand to a plain integer.
    if "e" in s.lower():
        try:
            s = f"{int(float(s)):d}"
        except Exception:
            return "Unclassified"

    # Drop a trailing float ".0" that Sheets/pandas adds to whole numbers.
    if s.endswith(".0"):
        s = s[:-2]

    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) < 7:
        return "Unclassified"
    return digits[5:7]


REPORT_MAX_MAP_SNIPPETS = 6  # keeps the report to one page — extra sections get a text note instead


def build_weekly_report_pdf(date_start, date_end, section_filter=None, meter_type_filter: str = "All"):
    """Builds a single-page PDF for sharing with the customer: install
    quantities by date and section code (parsed from each record's
    Consumer No / SNO), plus a small real-basemap snippet per section
    showing where those installs are. Pulls only from UploadedInstallLog —
    the same ledger the Dashboard/Installations totals are built from — so
    the numbers here always match the official install counts, never
    Map-only legacy data. Returns (pdf_bytes, error_message); pdf_bytes is
    None if error_message is set."""
    df = get_data("UploadedInstallLog")
    if df.empty or not has_col(df, "date", "sno", "meter_type"):
        return None, "No install data available yet."

    df = df.copy()
    df["_date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df[(df["_date"] >= date_start) & (df["_date"] <= date_end)]
    if meter_type_filter != "All":
        df = df[df["meter_type"].astype(str).str.strip() == meter_type_filter]
    df["section_code"] = df["sno"].apply(extract_section_code)
    if section_filter:
        df = df[df["section_code"].isin(section_filter)]

    if df.empty:
        return None, "No records match the selected filters."

    # Section name = the Location on the record; section code = the 2-digit
    # code parsed out of the SNO under that location. Map each code to the
    # location name(s) it appears under, for the report legend.
    code_to_location = {}
    if "location" in df.columns:
        for code, grp in df.groupby("section_code"):
            names = sorted({str(x).strip() for x in grp["location"] if str(x).strip() and str(x).strip() != "Unspecified"})
            if names:
                code_to_location[code] = " / ".join(names[:2]) + ("..." if len(names) > 2 else "")

    # Quantity table: dates (rows) x section codes (columns)
    pivot = df.groupby(["_date", "section_code"]).size().unstack(fill_value=0)
    pivot = pivot.sort_index()
    present_codes = list(pivot.columns)
    section_codes_sorted = sorted([s for s in present_codes if s != "Unclassified"]) + (["Unclassified"] if "Unclassified" in present_codes else [])
    pivot = pivot[section_codes_sorted]
    pivot["Total"] = pivot.sum(axis=1)
    total_row = pivot.sum(axis=0)
    total_row.name = "TOTAL"
    pivot_display = pd.concat([pivot, pd.DataFrame([total_row])])

    # Map snippet per section code, using only records with valid lat/long.
    df["_lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["_long"] = pd.to_numeric(df["long"], errors="coerce")
    section_qty = df["section_code"].value_counts()
    snippets = []  # (section_code, qty, png_bytes_or_None)
    for sec in sorted(section_codes_sorted, key=lambda s: section_qty.get(s, 0), reverse=True):
        sub = df[(df["section_code"] == sec) & df["_lat"].notna() & df["_long"].notna() & (df["_lat"] != 0) & (df["_long"] != 0)]
        qty = int(section_qty.get(sec, 0))
        png = None
        if not sub.empty:
            try:
                loc_name = code_to_location.get(sec, "")
                png = build_basemap_snapshot_png(sub["_lat"].tolist(), sub["_long"].tolist(), title=f"{sec} - {loc_name}" if loc_name else f"Section {sec}")
            except Exception:
                png = None
        snippets.append((sec, qty, png))

    shown_snippets = [s for s in snippets if s[2] is not None][:REPORT_MAX_MAP_SNIPPETS]
    omitted_count = len([s for s in snippets if s[2] is not None]) - len(shown_snippets)
    no_geo_sections = [s[0] for s in snippets if s[2] is None]

    # ── Build the PDF ────────────────────────────────────────────────────
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    pdf.set_margins(12, 12, 12)

    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(16, 21, 31)
    pdf.cell(0, 9, "Weekly Installation Report", ln=1)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 105, 115)
    sections_desc = "All Sections" if not section_filter else ", ".join(section_filter)
    pdf.cell(0, 6, f"Period: {date_start.isoformat()} to {date_end.isoformat()}   |   Meter Type: {meter_type_filter}   |   Sections: {sections_desc}", ln=1)
    pdf.cell(0, 5, f"Generated: {date.today().isoformat()}", ln=1)
    pdf.ln(3)

    # -- Quantity table --
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(16, 21, 31)
    pdf.cell(0, 6, "Installation Quantities By Date & Section", ln=1)
    col_labels = ["Date"] + section_codes_sorted + ["Total"]
    avail_w = pdf.w - pdf.l_margin - pdf.r_margin
    row_h = 6.5

    # The Date column needs a fixed width ("2026-09-06" won't fit in an even
    # split once there are several sections); the rest share what's left.
    date_col_w = 24.0
    n_code_cols = len(section_codes_sorted) + 1  # + Total
    code_col_w = max(11.0, (avail_w - date_col_w) / n_code_cols)
    # If many sections push the table past the page, scale everything down
    # rather than letting cells clip their text.
    table_w = date_col_w + code_col_w * n_code_cols
    if table_w > avail_w:
        scale = avail_w / table_w
        date_col_w *= scale
        code_col_w *= scale
    # Font small enough that the widest value still fits its cell.
    body_font = 9 if code_col_w >= 14 else (8 if code_col_w >= 12 else 7)

    def _fit(txt, width, size):
        """Trim a label so it can't overflow (and visibly clip) its cell."""
        txt = str(txt)
        pdf.set_font_size(size)
        while txt and pdf.get_string_width(txt) > width - 1.5:
            txt = txt[:-1]
        return txt

    pdf.set_font("Helvetica", "B", body_font)
    pdf.set_fill_color(16, 21, 31)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(date_col_w, row_h, _fit("Date", date_col_w, body_font), border=1, align="C", fill=True)
    for label in section_codes_sorted + ["Total"]:
        pdf.cell(code_col_w, row_h, _fit(label, code_col_w, body_font), border=1, align="C", fill=True)
    pdf.ln(row_h)

    for i, (idx, row) in enumerate(pivot_display.iterrows()):
        is_total = (idx == "TOTAL")
        pdf.set_font("Helvetica", "B" if is_total else "", body_font)
        if is_total:
            pdf.set_fill_color(230, 247, 240)
        else:
            pdf.set_fill_color(255, 255, 255) if i % 2 == 0 else pdf.set_fill_color(246, 247, 249)
        pdf.set_text_color(16, 21, 31)
        label = "TOTAL" if is_total else str(idx)
        pdf.cell(date_col_w, row_h, _fit(label, date_col_w, body_font), border=1, align="C", fill=True)
        for sec in section_codes_sorted:
            pdf.cell(code_col_w, row_h, str(int(row[sec])), border=1, align="C", fill=True)
        pdf.cell(code_col_w, row_h, str(int(row["Total"])), border=1, align="C", fill=True)
        pdf.ln(row_h)

    pdf.ln(2)

    # Section code -> Section name (Location) legend, so the customer can read
    # the coded columns above.
    if code_to_location:
        legend = "   ".join(f"{code} = {name}" for code, name in code_to_location.items() if code in section_codes_sorted)
        if legend:
            pdf.set_font("Helvetica", "", 7.5)
            pdf.set_text_color(100, 105, 115)
            pdf.multi_cell(avail_w, 4, f"Sections:  {legend}")
            pdf.ln(1)

    # -- Map snippets grid (fits remaining space on this one page) --
    if shown_snippets:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "Section Locations", ln=1)

        n_images = len(shown_snippets)
        n_cols_grid = min(3, n_images)
        n_rows_grid = math.ceil(n_images / n_cols_grid)
        gap = 4
        thumb_w = (avail_w - gap * (n_cols_grid - 1)) / n_cols_grid
        remaining_h = pdf.h - pdf.get_y() - pdf.b_margin - 12  # leave room for a footer note
        caption_h = 5
        thumb_h = max(28, min(45, remaining_h / n_rows_grid - caption_h))

        start_x, start_y = pdf.get_x(), pdf.get_y()
        for i, (sec, qty, png) in enumerate(shown_snippets):
            col, row = i % n_cols_grid, i // n_cols_grid
            x = start_x + col * (thumb_w + gap)
            y = start_y + row * (thumb_h + caption_h + gap)
            try:
                pdf.image(io.BytesIO(png), x=x, y=y, w=thumb_w, h=thumb_h)
            except Exception:
                pdf.set_xy(x, y)
                pdf.set_font("Helvetica", "", 8)
                pdf.multi_cell(thumb_w, 5, f"(Section {sec} map unavailable)", border=1)
            pdf.set_xy(x, y + thumb_h + 0.5)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(16, 21, 31)
            cap_loc = code_to_location.get(sec, "")
            cap = f"{sec} - {cap_loc} ({qty})" if cap_loc else f"Section {sec} - {qty} installs"
            pdf.set_font_size(8)
            while cap and pdf.get_string_width(cap) > thumb_w - 1 and len(cap) > 10:
                cap = cap[:-1]
            pdf.cell(thumb_w, caption_h, cap, align="C")
        pdf.set_y(start_y + n_rows_grid * (thumb_h + caption_h + gap))

    notes = []
    if omitted_count:
        notes.append(f"+{omitted_count} more section(s) with location data not shown here (see the Map tab for the full picture).")
    if no_geo_sections:
        notes.append(f"No location data on file yet for section(s): {', '.join(no_geo_sections)}.")
    if notes:
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(120, 125, 135)
        for n in notes:
            pdf.multi_cell(0, 4, n)

    return bytes(pdf.output()), None


def normalize_date_val(val):
    """Return an ISO date string (YYYY-MM-DD) or None."""
    if val is None:
        return None
    try:
        if isinstance(val, datetime):
            return val.date().isoformat()
        if isinstance(val, date):
            return val.isoformat()
        s = str(val).strip()
        if not s:
            return None
        parsed = pd.to_datetime(s, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date().isoformat()
    except Exception:
        return None


def normalize_time_val(val):
    """Return a zero-padded HH:MM:SS string or None."""
    if val is None:
        return None
    try:
        if isinstance(val, datetime):
            return val.strftime("%H:%M:%S")
        if isinstance(val, dtime):
            return val.strftime("%H:%M:%S")
        s = str(val).strip()
        if not s:
            return None
        parsed = pd.to_datetime(s, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.strftime("%H:%M:%S")
    except Exception:
        return None


def load_first_data_sheet(uploaded_file):
    """Return the primary data worksheet from an uploaded workbook, skipping
    any pre-computed pivot/summary sheets (e.g. 'LoginID_Summary')."""
    wb = openpyxl.load_workbook(uploaded_file, data_only=True)
    for name in wb.sheetnames:
        if "summary" not in name.strip().lower():
            return wb[name]
    return wb[wb.sheetnames[0]]


def time_to_minutes(hhmmss: str) -> float:
    h, m, s = hhmmss.split(":")
    return int(h) * 60 + int(m) + int(s) / 60.0


TREND_WINDOW_HOURS = 1      # how many of the most-recent hours count as "recent" for the trend signal
TREND_MIN_SAMPLE = 5        # minimum team-wide installs in that window before trusting it
TREND_CLAMP_MIN, TREND_CLAMP_MAX = 0.5, 1.5  # caps how much one hot/slow spell can swing the forecast


def compute_team_trend_multiplier(day_df: pd.DataFrame) -> float:
    """Team-wide momentum signal: installs/hour across ALL active installers
    in the last TREND_WINDOW_HOURS hours of activity, compared against the
    team's own average installs/hour for the day so far. Below 1.0 means the
    team has slowed down recently vs. its own day average; above 1.0 means
    it's sped up. The most recent active hour is almost always partial (data
    only ever runs up to whenever the last install happened, not a clean
    hour boundary) — both the day-average and the recent-window rates are
    normalized by actual ELAPSED minutes rather than assuming a full 60
    minutes for that hour, otherwise a normal pace in a half-elapsed hour
    looks like a fake slowdown. Requires at least TREND_MIN_SAMPLE team-wide
    installs in the recent window to trust it (otherwise returns 1.0 — no
    adjustment, too little data to read a trend from) and clamps to
    [TREND_CLAMP_MIN, TREND_CLAMP_MAX] so one unusually slow or fast hour
    can't swing the whole day's forecast on its own."""
    valid = day_df.dropna(subset=["hour_int"])
    if valid.empty:
        return 1.0
    active_hours = sorted(valid["hour_int"].unique())
    if len(active_hours) < 2:
        return 1.0  # not enough distinct hours yet to compare "recent" vs "day so far"

    last_hour = active_hours[-1]
    last_time_in_hour = valid[valid["hour_int"] == last_hour]["time"].max()
    _, mm, ss = last_time_in_hour.split(":")
    elapsed_frac_last_hour = max((int(mm) + int(ss) / 60) / 60.0, 1 / 60)  # fraction of that hour actually elapsed

    hours_elapsed_total = (len(active_hours) - 1) + elapsed_frac_last_hour
    if hours_elapsed_total <= 0:
        return 1.0
    day_avg_rate = len(valid) / hours_elapsed_total

    recent_hours = active_hours[-TREND_WINDOW_HOURS:]
    recent_count = len(valid[valid["hour_int"].isin(recent_hours)])
    if recent_count < TREND_MIN_SAMPLE:
        return 1.0  # too few recent installs team-wide to trust a trend read

    hours_elapsed_recent = (len(recent_hours) - 1) + elapsed_frac_last_hour if last_hour in recent_hours else len(recent_hours)
    hours_elapsed_recent = max(hours_elapsed_recent, elapsed_frac_last_hour)

    recent_rate = recent_count / hours_elapsed_recent
    multiplier = recent_rate / day_avg_rate
    return max(TREND_CLAMP_MIN, min(TREND_CLAMP_MAX, multiplier))


def forecast_total_installs(day_df: pd.DataFrame, installers: list, day_end_str: str = FORECAST_DAY_END):
    """Projects the team's likely total installs by day-end. Combines two
    signals: each active installer's own pace (avg minutes/install so far,
    same span/count formula as the Average Install Time table) as the
    baseline, adjusted by a team-wide trend multiplier (see
    compute_team_trend_multiplier) that reflects whether the WHOLE team has
    recently sped up or slowed down vs. its own day average — catching
    systemic shifts (post-lunch dip, a hard section, weather) that one
    installer's own history alone wouldn't show. An installer with only 1
    install today has no pace of their own — falls back to the team's
    average pace across installers with >=2 installs. If NO installer has
    >=2 installs yet, there's no pace to extrapolate from at all, and this
    returns (None, 1.0) — caller should show "not enough data yet" rather
    than a fabricated number. Returns (rounded_total, trend_multiplier)."""
    day_end_min = time_to_minutes(day_end_str)
    trend_multiplier = compute_team_trend_multiplier(day_df)

    per_installer = []  # (count, own_pace_or_None, last_install_minutes)
    paces = []
    for inst in installers:
        sub = day_df[day_df["installer_id"] == inst].sort_values("time")
        n = len(sub)
        first_t, last_t = sub["time"].iloc[0], sub["time"].iloc[-1]
        last_min = time_to_minutes(last_t)
        own_pace = None
        if n >= 2:
            span_min = time_to_minutes(last_t) - time_to_minutes(first_t)
            # N installs span only N-1 gaps — dividing by N understates the
            # true minutes-per-install and over-forecasts (worst at small N).
            own_pace = span_min / (n - 1)
            if own_pace > 0:
                paces.append(own_pace)
        per_installer.append((n, own_pace, last_min))

    if not paces:
        return None, 1.0  # nobody has an established pace yet — too early to project

    team_avg_pace = sum(paces) / len(paces)

    total_forecast = 0.0
    for n, own_pace, last_min in per_installer:
        base_pace = own_pace if own_pace else team_avg_pace
        adjusted_pace = base_pace / trend_multiplier  # slower team trend -> more minutes/install -> fewer projected
        remaining_min = max(0.0, day_end_min - last_min)
        projected_additional = (remaining_min / adjusted_pace) if adjusted_pace > 0 else 0.0
        total_forecast += n + projected_additional

    return round(total_forecast), trend_multiplier


# ── Shared data fetched once per run (avoids repeat reads across tabs) ──────
df_installations_master = get_data("Installations")
df_inventory_master = get_data("Inventory")
df_technicians_master = get_data("Technicians")
df_locations_master = get_data("Locations")

active_techs = []
if not df_technicians_master.empty and has_col(df_technicians_master, "is_active", "name"):
    for _, r in df_technicians_master.iterrows():
        if str(r["is_active"]).strip().lower() in ["1", "1.0", "true", "yes"]:
            n = str(r["name"]).strip()
            if n:
                active_techs.append(n)

active_locs = []
if not df_locations_master.empty and "location_name" in df_locations_master.columns:
    for _, r in df_locations_master.iterrows():
        l = str(r["location_name"]).strip()
        if l:
            active_locs.append(l)

# Installer LoginID -> Technician display name, from the optional "login_id"
# column on the Technicians sheet. Unmapped logins fall back to the raw ID.
tech_login_lookup = {}
# Reverse of the above: technician display name -> their login_id, used to
# standardize manual entries onto the same login-ID identity as uploads.
name_to_login_id = {}
if not df_technicians_master.empty and has_col(df_technicians_master, "login_id", "name"):
    for _, r in df_technicians_master.iterrows():
        lid = str(r.get("login_id", "")).strip()
        nm = str(r.get("name", "")).strip()
        if lid and nm:
            tech_login_lookup[lid.lower()] = nm
            name_to_login_id[nm] = lid


def _execute_push(parsed_records, source_label="install(s)"):
    """The actual write logic — no double-count risk gating. Called either
    directly (no risk detected) or after the supervisor explicitly confirms
    past a detected risk via the pending-confirmation banner."""
    if not parsed_records:
        st.warning("⚠️ No records to push.")
        return

    # Defense-in-depth: every caller already filters to INSTALLER_ID_PREFIX
    # (TL_) before parsing, but enforce it here too so the rule holds even if
    # a future caller forgets.
    non_tl_filtered = sum(1 for rec in parsed_records if not is_valid_installer_id(rec.get("installer_id")))
    parsed_records = [rec for rec in parsed_records if is_valid_installer_id(rec.get("installer_id"))]
    if not parsed_records:
        st.warning(f"⚠️ No {INSTALLER_ID_PREFIX} installer records to push.")
        return

    detail_cols = ["location", "meter_type", "sno", "old_meter_no", "new_meter_no", "lat", "long"]
    df_log_existing = get_data("UploadedInstallLog")
    if df_log_existing.empty:
        df_log_existing = pd.DataFrame(columns=["key", "date", "time", "installer_id", "tech_name", "source"] + detail_cols)
    for col in detail_cols + ["source"]:
        if col not in df_log_existing.columns:
            df_log_existing[col] = ""

    existing_keys = set(df_log_existing["key"].values) if "key" in df_log_existing.columns else set()
    key_to_idx = {k: i for i, k in zip(df_log_existing.index, df_log_existing["key"].values)} if "key" in df_log_existing.columns else {}

    new_log_rows = []
    dates_seen, dates_with_new, unmapped_ids = set(), set(), set()
    backfilled_count = 0
    for rec in parsed_records:
        dates_seen.add(rec["date"])
        key = f"{rec['date']}||{rec['time']}||{rec['installer_id']}"
        if key in existing_keys:
            idx = key_to_idx[key]
            filled_something = False
            for col in detail_cols:
                new_val = rec.get(col)
                if new_val in (None, ""):
                    continue
                existing_val = df_log_existing.at[idx, col]
                existing_blank = existing_val in (None, "", "Unspecified") or (isinstance(existing_val, float) and pd.isna(existing_val))
                if existing_blank:
                    df_log_existing.at[idx, col] = str(new_val)
                    filled_something = True
            if filled_something:
                backfilled_count += 1
            continue
        existing_keys.add(key)
        tech_name = tech_login_lookup.get(rec["installer_id"].lower())
        if tech_name is None:
            tech_name = rec["installer_id"]
            unmapped_ids.add(rec["installer_id"])
        new_log_rows.append({
            "key": key, "date": rec["date"], "time": rec["time"],
            "installer_id": rec["installer_id"], "tech_name": tech_name,
            "location": rec.get("location") or "Unspecified",
            "meter_type": rec.get("meter_type") or "",
            "sno": rec.get("sno") or "", "old_meter_no": rec.get("old_meter_no") or "",
            "new_meter_no": rec.get("new_meter_no") or "",
            "lat": rec.get("lat") or "", "long": rec.get("long") or "",
            "source": source_label,
        })
        dates_with_new.add(rec["date"])

    fully_dup_dates = dates_seen - dates_with_new

    if not new_log_rows and not backfilled_count:
        st.error(f"❌ Installs already exist for: {', '.join(sorted(dates_seen))}, with no missing details to fill in. Nothing to update.")
        return

    # 1) append/update raw log rows (dedup + detail ledger)
    updated_log = pd.concat([df_log_existing, pd.DataFrame(new_log_rows)], ignore_index=True) if new_log_rows else df_log_existing

    if not new_log_rows:
        if safe_update("UploadedInstallLog", updated_log):
            st.success(f"✅ No new installs, but filled in missing details for {backfilled_count} existing record(s).")
            st.rerun()
        return

    # 2) aggregate the NEW rows only, by date + tech_name + location
    new_log_df = pd.DataFrame(new_log_rows)
    new_log_df["is_1ph"] = new_log_df["meter_type"].str.contains("1", na=False)
    new_log_df["is_3ph"] = new_log_df["meter_type"].str.contains("3", na=False)
    unclassified = int((~new_log_df["is_1ph"] & ~new_log_df["is_3ph"]).sum())
    agg = new_log_df.groupby(["date", "tech_name", "location"]).agg(
        d_1ph=("is_1ph", "sum"), d_3ph=("is_3ph", "sum"), installer_id=("installer_id", "first")
    ).reset_index()

    # 3) merge deltas into Installations sheet
    df_inst_existing = get_data("Installations")
    if df_inst_existing.empty:
        df_inst_existing = pd.DataFrame(columns=["date", "tech_name", "installer_id", "location", "qty_1ph", "qty_3ph"])
    for col in ["qty_1ph", "qty_3ph"]:
        if col in df_inst_existing.columns:
            df_inst_existing[col] = pd.to_numeric(df_inst_existing[col], errors="coerce").fillna(0).astype(int)
    if "installer_id" not in df_inst_existing.columns:
        df_inst_existing["installer_id"] = ""

    for _, arow in agg.iterrows():
        mask = (
            (df_inst_existing.get("date") == arow["date"]) &
            (df_inst_existing.get("tech_name") == arow["tech_name"]) &
            (df_inst_existing.get("location") == arow["location"])
        ) if not df_inst_existing.empty else pd.Series([], dtype=bool)
        if not df_inst_existing.empty and mask.any():
            df_inst_existing.loc[mask, "qty_1ph"] += int(arow["d_1ph"])
            df_inst_existing.loc[mask, "qty_3ph"] += int(arow["d_3ph"])
            # Backfill installer_id on a matching row that predates this field (e.g. old manual entries).
            blank_id_mask = mask & (df_inst_existing["installer_id"].astype(str).str.strip() == "")
            if blank_id_mask.any():
                df_inst_existing.loc[blank_id_mask, "installer_id"] = arow["installer_id"]
        else:
            df_inst_existing = pd.concat([df_inst_existing, pd.DataFrame([{
                "date": arow["date"], "tech_name": arow["tech_name"], "installer_id": arow["installer_id"], "location": arow["location"],
                "qty_1ph": int(arow["d_1ph"]), "qty_3ph": int(arow["d_3ph"]),
            }])], ignore_index=True)

    if safe_update("Installations", df_inst_existing) and safe_update("UploadedInstallLog", updated_log):
        map_added, map_ok = mirror_records_to_map(new_log_rows)
        if not map_ok:
            st.session_state["map_sync_warning"] = (
                f"⚠️ {len(new_log_rows)} install(s) were saved to Installs data, but syncing them to the "
                "Map tab failed. This almost always means the 'MapRecords' worksheet tab doesn't exist yet "
                "in your Google Sheet — add it (same columns as UploadedInstallLog: key, date, time, "
                "installer_id, tech_name, location, sno, old_meter_no, new_meter_no, lat, long), then "
                "re-upload the same file to backfill the map."
            )
        st.success(f"✅ Added {len(new_log_rows)} new {source_label} across {len(dates_with_new)} date(s).")
        if backfilled_count:
            st.info(f"ℹ️ Also filled in missing details for {backfilled_count} existing record(s).")
        if fully_dup_dates:
            st.warning(f"⚠️ Already fully recorded, skipped: {', '.join(sorted(fully_dup_dates))}")
        if unmapped_ids:
            st.info(f"ℹ️ No technician mapping found for: {', '.join(sorted(unmapped_ids))} — used their login ID as the name. Add a 'login_id' to that technician in Admin to map it to a display name next time.")
        if unclassified:
            st.warning(f"⚠️ {unclassified} record(s) had no meter type on file and weren't counted toward 1PH/3PH totals.")
        if non_tl_filtered:
            st.warning(f"⚠️ {non_tl_filtered} record(s) with a non-{INSTALLER_ID_PREFIX} installer ID were filtered out and not saved.")
        st.rerun()


def mirror_records_to_map(records) -> tuple:
    """One-way sync: install data pushed into Installations — via the
    Installs-tab bulk upload, the Installs-tab Legacy Data upload, or the
    Analytics 'Update Installs' push — also lands in MapRecords so it shows
    up on the Map tab. This never runs in the other direction: the Map tab's
    own Legacy Data upload writes only to MapRecords and never calls this or
    touches Installations/UploadedInstallLog at all.
    Returns (added_count, ok) — ok is False if the write to MapRecords
    itself failed (most commonly because the 'MapRecords' worksheet tab
    doesn't exist yet in the Google Sheet)."""
    if not records:
        return 0, True
    map_cols = ["key", "date", "time", "installer_id", "tech_name", "location", "sno", "old_meter_no", "new_meter_no", "lat", "long"]
    df_map_existing = get_data("MapRecords")
    if df_map_existing.empty:
        df_map_existing = pd.DataFrame(columns=map_cols)
    for col in map_cols:
        if col not in df_map_existing.columns:
            df_map_existing[col] = ""
    existing_keys = set(df_map_existing["key"].values) if "key" in df_map_existing.columns else set()

    new_map_rows = []
    for rec in records:
        key = rec.get("key") or f"{rec.get('date')}||{rec.get('time')}||{rec.get('installer_id')}"
        if key in existing_keys:
            continue
        existing_keys.add(key)
        row = {col: rec.get(col, "") for col in map_cols}
        row["key"] = key
        new_map_rows.append(row)

    if not new_map_rows:
        return 0, True
    updated_map = pd.concat([df_map_existing, pd.DataFrame(new_map_rows)], ignore_index=True)
    ok = safe_update("MapRecords", updated_map)
    return len(new_map_rows), ok


def push_parsed_records_to_installations(parsed_records, source_label="install(s)"):
    """Entry point used by all upload paths (Installs bulk upload, Legacy Data
    upload, Analytics 'Update Installs'). Before writing anything, checks for
    a specific double-count risk: merging new upload records onto a
    date+technician+location combo whose current Installations quantity has
    ZERO backing rows in UploadedInstallLog — meaning that quantity came
    entirely from a manual entry. Adding on top of it blindly could double
    count the same real installs the supervisor already logged by hand. If
    that risk is found, the push is held for one explicit confirmation
    (rendered as a banner near the top of the app) instead of silently
    merging. If a combo already has upload history, adding more is treated as
    legitimate additional installs and proceeds immediately, same as before."""
    if not parsed_records:
        st.warning("⚠️ No records to push.")
        return

    valid_records = [rec for rec in parsed_records if is_valid_installer_id(rec.get("installer_id"))]
    if not valid_records:
        st.warning(f"⚠️ No {INSTALLER_ID_PREFIX} installer records to push.")
        return

    df_log_existing = get_data("UploadedInstallLog")
    existing_keys = set(df_log_existing["key"].values) if not df_log_existing.empty and "key" in df_log_existing.columns else set()
    candidate_new = [rec for rec in valid_records if f"{rec['date']}||{rec['time']}||{rec['installer_id']}" not in existing_keys]

    risky = []
    if candidate_new:
        tmp_df = pd.DataFrame(candidate_new)
        tmp_df["tech_name"] = tmp_df["installer_id"].apply(lambda x: tech_login_lookup.get(str(x).lower(), x))
        if "location" in tmp_df.columns:
            tmp_df["location"] = tmp_df["location"].apply(lambda x: x if x else "Unspecified")
        else:
            tmp_df["location"] = "Unspecified"
        grp = tmp_df.groupby(["date", "tech_name", "location"]).size().reset_index(name="new_count")

        df_inst_existing = get_data("Installations")
        log_has_cols = not df_log_existing.empty and has_col(df_log_existing, "date", "tech_name", "location")
        inst_has_cols = not df_inst_existing.empty and has_col(df_inst_existing, "date", "tech_name", "location", "qty_1ph", "qty_3ph")

        for _, row in grp.iterrows():
            prior_mask = (
                (df_log_existing["date"] == row["date"]) & (df_log_existing["tech_name"] == row["tech_name"]) & (df_log_existing["location"] == row["location"])
            ) if log_has_cols else pd.Series([], dtype=bool)
            if int(prior_mask.sum()) > 0:
                continue  # this combo already has upload provenance — safe to add more

            inst_mask = (
                (df_inst_existing["date"] == row["date"]) & (df_inst_existing["tech_name"] == row["tech_name"]) & (df_inst_existing["location"] == row["location"])
            ) if inst_has_cols else pd.Series([], dtype=bool)
            if inst_mask.any():
                existing_qty = int(
                    pd.to_numeric(df_inst_existing.loc[inst_mask, "qty_1ph"], errors="coerce").fillna(0).sum()
                    + pd.to_numeric(df_inst_existing.loc[inst_mask, "qty_3ph"], errors="coerce").fillna(0).sum()
                )
                if existing_qty > 0:
                    risky.append({
                        "Date": row["date"], "Technician": row["tech_name"], "Location": row["location"],
                        "Existing Qty (manual entry, no upload history)": existing_qty,
                        "New From This Upload": int(row["new_count"]),
                    })

    if risky:
        st.session_state["pending_push"] = {"records": parsed_records, "source_label": source_label, "risky": risky}
        st.rerun()
        return

    _execute_push(parsed_records, source_label)


def diagnose_installations_discrepancy():
    """Compares each Installations row's quantity against what's purely
    derivable from UploadedInstallLog for that same date+technician+location.
    A row with upload history whose Installations total EXCEEDS its
    upload-derived total suggests a manual entry sitting on top of (and
    possibly duplicating) already-uploaded records — the same pattern the
    push-time risk check (added above) now guards against going forward.
    This surfaces it for anything saved before that check existed."""
    df_inst = get_data("Installations")
    df_log = get_data("UploadedInstallLog")
    if df_inst.empty or not has_col(df_inst, "date", "tech_name", "location", "qty_1ph", "qty_3ph"):
        return pd.DataFrame()

    df_inst = df_inst.copy()
    for col in ["qty_1ph", "qty_3ph"]:
        df_inst[col] = pd.to_numeric(df_inst[col], errors="coerce").fillna(0).astype(int)
    df_inst["Installations Qty"] = df_inst["qty_1ph"] + df_inst["qty_3ph"]

    if not df_log.empty and has_col(df_log, "date", "tech_name", "location"):
        log_counts = df_log.groupby(["date", "tech_name", "location"]).size().reset_index(name="Upload-Derived Qty")
    else:
        log_counts = pd.DataFrame(columns=["date", "tech_name", "location", "Upload-Derived Qty"])

    merged = df_inst.merge(log_counts, on=["date", "tech_name", "location"], how="left")
    merged["Upload-Derived Qty"] = merged["Upload-Derived Qty"].fillna(0).astype(int)
    merged["Implied Manual Qty"] = merged["Installations Qty"] - merged["Upload-Derived Qty"]

    flagged = merged[(merged["Upload-Derived Qty"] > 0) & (merged["Implied Manual Qty"] > 0)].copy()
    return flagged[["date", "tech_name", "location", "Installations Qty", "Upload-Derived Qty", "Implied Manual Qty"]].rename(
        columns={"date": "Date", "tech_name": "Technician", "location": "Location"}
    ).sort_values("Implied Manual Qty", ascending=False)


def find_sno_duplicates():
    """The highest-confidence duplicate signal: the same Consumer No (SNO)
    appearing more than once in UploadedInstallLog on the SAME date. A given
    service number shouldn't legitimately get a fresh install twice in one
    day — this almost always means the same real install was uploaded twice
    (e.g. once via the regular bulk upload, again via a Legacy Data upload,
    possibly with a slightly different parsed time producing a different
    dedup key). Returns a DataFrame with one row per duplicate record,
    grouped/sorted so each SNO+date cluster sits together, plus a 'Keep?'
    column pre-set to keep only the earliest time in each cluster."""
    df_log = get_data("UploadedInstallLog")
    if df_log.empty or not has_col(df_log, "sno", "date", "time", "key"):
        return pd.DataFrame()

    sno_df = df_log[df_log["sno"].astype(str).str.strip() != ""].copy()
    if sno_df.empty:
        return pd.DataFrame()

    dup_mask = sno_df.duplicated(subset=["sno", "date"], keep=False)
    dups = sno_df[dup_mask].sort_values(["sno", "date", "time"]).copy()
    if dups.empty:
        return pd.DataFrame()

    # Default: keep the earliest record in each SNO+date cluster, flag the rest for removal.
    dups["Keep?"] = ~dups.duplicated(subset=["sno", "date"], keep="first")
    cols = ["key", "sno", "date", "time", "tech_name", "location", "meter_type", "old_meter_no", "new_meter_no", "Keep?"]
    cols = [c for c in cols if c in dups.columns]
    return dups[cols].rename(columns={
        "key": "Key", "sno": "SNO", "date": "Date", "time": "Time", "tech_name": "Technician",
        "location": "Location", "meter_type": "Meter Type", "old_meter_no": "Old Meter No", "new_meter_no": "New Meter No",
    })


def find_near_time_duplicates(threshold_seconds: int = 120):
    """Lower-confidence signal: the same installer with two records on the
    same date whose times are within threshold_seconds of each other —
    can indicate the same real install parsed twice with slightly different
    time precision (no SNO to cross-check against). For manual review only —
    no default selection, since two genuinely fast back-to-back installs by
    the same installer are also possible."""
    df_log = get_data("UploadedInstallLog")
    if df_log.empty or not has_col(df_log, "installer_id", "date", "time", "key"):
        return pd.DataFrame()

    flagged_idx = set()
    for (_inst, _d), g in df_log.groupby(["installer_id", "date"]):
        g = g.sort_values("time")
        try:
            secs = g["time"].apply(time_to_minutes) * 60
        except Exception:
            continue
        idx_list = g.index.tolist()
        vals = secs.tolist()
        for i in range(1, len(vals)):
            if (vals[i] - vals[i - 1]) < threshold_seconds:
                flagged_idx.add(idx_list[i - 1])
                flagged_idx.add(idx_list[i])

    if not flagged_idx:
        return pd.DataFrame()
    near = df_log.loc[sorted(flagged_idx)].sort_values(["installer_id", "date", "time"]).copy()
    near["Keep?"] = True  # no default removal suggestion — pure review
    cols = ["key", "installer_id", "tech_name", "date", "time", "location", "sno", "meter_type", "Keep?"]
    cols = [c for c in cols if c in near.columns]
    return near[cols].rename(columns={
        "key": "Key", "installer_id": "Installer LoginID", "tech_name": "Technician", "date": "Date",
        "time": "Time", "location": "Location", "sno": "SNO", "meter_type": "Meter Type",
    })


def find_matching_log_keys_from_file(uploaded_file):
    """Parses an uploaded file the same way as the bulk/legacy uploaders and
    returns the set of date+time+installer keys it would generate. Re-uploading
    the exact same file that was previously used (e.g. via the old Map-tab
    legacy upload, before that was decoupled from Installations) lets us
    identify precisely which existing UploadedInstallLog rows came from that
    specific upload, since key generation is fully deterministic from the
    file's contents. Returns None if the file's headers can't be parsed."""
    try:
        ws = load_first_data_sheet(uploaded_file)
    except Exception:
        return None
    header_row, col_map = find_header_row(ws, INSTALL_BULK_REQUIRED_HEADERS)
    if header_row is None:
        return None
    keys = set()
    for r in range(header_row + 1, ws.max_row + 1):
        raw_installer = ws.cell(row=r, column=col_map["Installer LoginID"]).value
        if raw_installer is None or str(raw_installer).strip() == "":
            continue
        if not is_valid_installer_id(raw_installer):
            continue
        d = normalize_date_val(ws.cell(row=r, column=col_map["Installation Date"]).value)
        t = normalize_time_val(ws.cell(row=r, column=col_map["Installation Time"]).value)
        if d is None or t is None:
            continue
        keys.add(f"{d}||{t}||{str(raw_installer).strip()}")
    return keys


def remove_install_log_rows(keys_to_remove) -> int:
    """Removes specific rows (by their 'key') from UploadedInstallLog and
    correctly reverses their 1PH/3PH counts back out of the Installations
    sheet, dropping any Installations row that lands at zero/zero. Returns
    the number of rows removed."""
    keys_to_remove = set(keys_to_remove)
    if not keys_to_remove:
        return 0
    df_log = get_data("UploadedInstallLog")
    if df_log.empty or "key" not in df_log.columns:
        return 0

    is_target = df_log["key"].isin(keys_to_remove)
    removed_rows = df_log[is_target].copy()
    removed_count = len(removed_rows)
    if removed_count == 0:
        return 0

    df_inst = get_data("Installations")
    if not df_inst.empty and has_col(df_inst, "date", "tech_name", "location", "qty_1ph", "qty_3ph"):
        for col in ["qty_1ph", "qty_3ph"]:
            df_inst[col] = pd.to_numeric(df_inst[col], errors="coerce").fillna(0).astype(int)
        if "meter_type" not in removed_rows.columns:
            removed_rows["meter_type"] = ""
        removed_rows["is_1ph"] = removed_rows["meter_type"].astype(str).str.contains("1", na=False)
        removed_rows["is_3ph"] = removed_rows["meter_type"].astype(str).str.contains("3", na=False)
        agg = removed_rows.groupby(["date", "tech_name", "location"]).agg(
            d_1ph=("is_1ph", "sum"), d_3ph=("is_3ph", "sum")
        ).reset_index()
        for _, arow in agg.iterrows():
            mask = (df_inst["date"] == arow["date"]) & (df_inst["tech_name"] == arow["tech_name"]) & (df_inst["location"] == arow["location"])
            if mask.any():
                df_inst.loc[mask, "qty_1ph"] = (df_inst.loc[mask, "qty_1ph"] - int(arow["d_1ph"])).clip(lower=0)
                df_inst.loc[mask, "qty_3ph"] = (df_inst.loc[mask, "qty_3ph"] - int(arow["d_3ph"])).clip(lower=0)
        df_inst = df_inst[~((df_inst["qty_1ph"] == 0) & (df_inst["qty_3ph"] == 0))].reset_index(drop=True)
        safe_update("Installations", df_inst)

    df_log_clean = df_log[~is_target].reset_index(drop=True)
    safe_update("UploadedInstallLog", df_log_clean)
    return removed_count


def find_map_duplicates():
    """Same-SNO-same-date duplicate check, scoped entirely to MapRecords
    (the Map tab's own independent data — never cross-checked against
    UploadedInstallLog/Installations)."""
    df_map = get_data("MapRecords")
    if df_map.empty or not has_col(df_map, "sno", "date", "time"):
        return pd.DataFrame()
    sno_df = df_map[df_map["sno"].astype(str).str.strip() != ""].copy()
    if sno_df.empty:
        return pd.DataFrame()
    dup_mask = sno_df.duplicated(subset=["sno", "date"], keep=False)
    dups = sno_df[dup_mask].sort_values(["sno", "date", "time"]).copy()
    if dups.empty:
        return pd.DataFrame()
    dups["Keep?"] = ~dups.duplicated(subset=["sno", "date"], keep="first")
    cols = ["key", "sno", "date", "time", "tech_name", "location", "old_meter_no", "new_meter_no", "Keep?"]
    cols = [c for c in cols if c in dups.columns]
    return dups[cols].rename(columns={
        "key": "Key", "sno": "SNO", "date": "Date", "time": "Time", "tech_name": "Technician",
        "location": "Location", "old_meter_no": "Old Meter No", "new_meter_no": "New Meter No",
    })


def remove_map_records(keys_to_remove) -> int:
    """Removes specific rows (by 'key') from MapRecords only. No
    Installations/UploadedInstallLog reversal needed — Map's own data never
    touches inventory counts."""
    keys_to_remove = set(keys_to_remove)
    if not keys_to_remove:
        return 0
    df_map = get_data("MapRecords")
    if df_map.empty or "key" not in df_map.columns:
        return 0
    is_target = df_map["key"].isin(keys_to_remove)
    removed = int(is_target.sum())
    if removed == 0:
        return 0
    safe_update("MapRecords", df_map[~is_target].reset_index(drop=True))
    return removed


def render_map_legacy_upload_widget():
    """Uploads legacy/historical data for the Map tab ONLY. Writes exclusively
    to MapRecords and never touches Installations or UploadedInstallLog — this
    is the fix for the earlier bug where Map-tab legacy uploads were merging
    into inventory counts. Dedupes within MapRecords by date+time+installer,
    then flags same-SNO-same-date duplicates for review."""
    st.markdown("""
    <div class="info-box">
    📍 Map-only. Adds pins here; does <b>not</b> affect Installations or inventory. Duplicates skipped.
    </div>
    """, unsafe_allow_html=True)
    legacy_file = st.file_uploader("Upload Legacy/Historical Excel (.xlsx) — Map Only", type=["xlsx"], key="map_legacy_uploader")
    if legacy_file is not None:
        if st.button("📥 Process Legacy Data (Map Only)", type="primary", use_container_width=True, key="map_legacy_process_btn"):
            try:
                ws = load_first_data_sheet(legacy_file)
            except Exception as e:
                st.error(f"❌ Could not open the file: {e}")
                ws = None

            if ws is not None:
                header_row, col_map = find_header_row(ws, INSTALL_BULK_REQUIRED_HEADERS)
                if header_row is None:
                    st.error("❌ Could not find 'Installation Date', 'Installation Time', 'Installer LoginID', 'Section' and 'New Meter Type' columns in this file.")
                else:
                    detail_optional_map = find_optional_cols(ws, header_row, list(DETAIL_FIELD_HEADERS.values()))
                    parsed = []
                    skipped_non_tl = 0
                    for r in range(header_row + 1, ws.max_row + 1):
                        raw_installer = ws.cell(row=r, column=col_map["Installer LoginID"]).value
                        if raw_installer is None or str(raw_installer).strip() == "":
                            continue
                        if not is_valid_installer_id(raw_installer):
                            skipped_non_tl += 1
                            continue
                        d = normalize_date_val(ws.cell(row=r, column=col_map["Installation Date"]).value)
                        t = normalize_time_val(ws.cell(row=r, column=col_map["Installation Time"]).value)
                        if d is None or t is None:
                            continue
                        section = ws.cell(row=r, column=col_map["Section"]).value
                        rec = {
                            "date": d, "time": t,
                            "installer_id": str(raw_installer).strip(),
                            "location": str(section).strip() if section else "Unspecified",
                        }
                        rec.update(extract_detail_fields(ws, r, detail_optional_map))
                        rec["tech_name"] = tech_login_lookup.get(rec["installer_id"].lower(), rec["installer_id"])
                        parsed.append(rec)

                    if not parsed:
                        st.warning(f"⚠️ No valid {INSTALLER_ID_PREFIX} installer rows with a date and time were found in this file.")
                    else:
                        if skipped_non_tl:
                            st.caption(f"ℹ️ Ignored {skipped_non_tl} row(s) with a non-{INSTALLER_ID_PREFIX} installer ID.")
                        added, map_ok = mirror_records_to_map(parsed)
                        if not map_ok:
                            st.error("❌ Failed to save to the Map. Make sure the 'MapRecords' worksheet tab exists in your Google Sheet (see the app's setup docstring for its columns), then try again.")
                        elif added == 0:
                            st.error("❌ All records in this file are already on the map. Nothing new to add.")
                        else:
                            st.success(f"✅ Added {added} new record(s) to the Map. Installations and inventory counts were not affected.")
                            dup_check = find_map_duplicates()
                            if not dup_check.empty:
                                st.warning(f"⚠️ {dup_check['SNO'].nunique()} SNO(s) now have more than one record on the same date in Map data. Review under Map tab \u2192 Data Maintenance if you want to remove any.")
                            st.rerun()


def cleanup_non_tl_records():
    """One-click removal of any records saved before the TL_ filter was
    standardized. Removes matching rows from UploadedInstallLog (and, for
    safety, AnalyticsRaw), and correctly reverses their 1PH/3PH counts back
    out of the Installations sheet — dropping any Installations row that
    lands at zero/zero as a result. Returns (removed_from_log, removed_from_analytics)."""
    removed_log = 0
    removed_araw = 0

    df_log = get_data("UploadedInstallLog")
    if not df_log.empty and "installer_id" in df_log.columns:
        is_bad = ~df_log["installer_id"].apply(is_valid_installer_id)
        bad_rows = df_log[is_bad].copy()
        removed_log = len(bad_rows)
        if removed_log:
            df_inst = get_data("Installations")
            if not df_inst.empty and has_col(df_inst, "date", "tech_name", "location", "qty_1ph", "qty_3ph"):
                for col in ["qty_1ph", "qty_3ph"]:
                    df_inst[col] = pd.to_numeric(df_inst[col], errors="coerce").fillna(0).astype(int)
                if "meter_type" not in bad_rows.columns:
                    bad_rows["meter_type"] = ""
                bad_rows["is_1ph"] = bad_rows["meter_type"].astype(str).str.contains("1", na=False)
                bad_rows["is_3ph"] = bad_rows["meter_type"].astype(str).str.contains("3", na=False)
                agg = bad_rows.groupby(["date", "tech_name", "location"]).agg(
                    d_1ph=("is_1ph", "sum"), d_3ph=("is_3ph", "sum")
                ).reset_index()
                for _, arow in agg.iterrows():
                    mask = (
                        (df_inst["date"] == arow["date"]) &
                        (df_inst["tech_name"] == arow["tech_name"]) &
                        (df_inst["location"] == arow["location"])
                    )
                    if mask.any():
                        df_inst.loc[mask, "qty_1ph"] = (df_inst.loc[mask, "qty_1ph"] - int(arow["d_1ph"])).clip(lower=0)
                        df_inst.loc[mask, "qty_3ph"] = (df_inst.loc[mask, "qty_3ph"] - int(arow["d_3ph"])).clip(lower=0)
                df_inst = df_inst[~((df_inst["qty_1ph"] == 0) & (df_inst["qty_3ph"] == 0))].reset_index(drop=True)
                safe_update("Installations", df_inst)
            df_log_clean = df_log[~is_bad].reset_index(drop=True)
            safe_update("UploadedInstallLog", df_log_clean)

    df_araw = get_data("AnalyticsRaw")
    if not df_araw.empty and "installer_id" in df_araw.columns:
        is_bad2 = ~df_araw["installer_id"].apply(is_valid_installer_id)
        removed_araw = int(is_bad2.sum())
        if removed_araw:
            df_araw_clean = df_araw[~is_bad2].reset_index(drop=True)
            safe_update("AnalyticsRaw", df_araw_clean)

    return removed_log, removed_araw


def render_legacy_upload_widget(key_prefix: str):
    """A 'Upload Legacy/Historical Data' widget, reused on both the Map tab
    and the Installs tab. Parses the same MDM export column layout as the
    regular bulk upload (Installation Date/Time/Installer LoginID/Section/
    New Meter Type + the optional detail columns), then pushes through the
    exact same dedup/backfill/merge pipeline — so historical data is checked
    for duplicates against everything already recorded and only new records
    (or missing details) are added."""
    st.markdown("""
    <div class="info-box">
    For older records. Duplicates are skipped — only new rows are added.
    </div>
    """, unsafe_allow_html=True)
    legacy_file = st.file_uploader("Upload Legacy/Historical Excel (.xlsx)", type=["xlsx"], key=f"{key_prefix}_legacy_uploader")
    if legacy_file is not None:
        if st.button("📥 Process Legacy Data", type="primary", use_container_width=True, key=f"{key_prefix}_legacy_process_btn"):
            try:
                ws = load_first_data_sheet(legacy_file)
            except Exception as e:
                st.error(f"❌ Could not open the file: {e}")
                ws = None

            if ws is not None:
                header_row, col_map = find_header_row(ws, INSTALL_BULK_REQUIRED_HEADERS)
                if header_row is None:
                    st.error("❌ Could not find 'Installation Date', 'Installation Time', 'Installer LoginID', 'Section' and 'New Meter Type' columns in this file.")
                else:
                    detail_optional_map = find_optional_cols(ws, header_row, list(DETAIL_FIELD_HEADERS.values()))
                    parsed = []
                    skipped_non_tl = 0
                    for r in range(header_row + 1, ws.max_row + 1):
                        raw_installer = ws.cell(row=r, column=col_map["Installer LoginID"]).value
                        if raw_installer is None or str(raw_installer).strip() == "":
                            continue
                        if not is_valid_installer_id(raw_installer):
                            skipped_non_tl += 1
                            continue
                        d = normalize_date_val(ws.cell(row=r, column=col_map["Installation Date"]).value)
                        t = normalize_time_val(ws.cell(row=r, column=col_map["Installation Time"]).value)
                        if d is None or t is None:
                            continue
                        section = ws.cell(row=r, column=col_map["Section"]).value
                        mtype = ws.cell(row=r, column=col_map["New Meter Type"]).value
                        rec = {
                            "date": d, "time": t,
                            "installer_id": str(raw_installer).strip(),
                            "location": str(section).strip() if section else "Unspecified",
                            "meter_type": str(mtype).strip() if mtype else "",
                        }
                        rec.update(extract_detail_fields(ws, r, detail_optional_map))
                        parsed.append(rec)

                    if not parsed:
                        st.warning(f"⚠️ No valid {INSTALLER_ID_PREFIX} installer rows with a date and time were found in this file.")
                    else:
                        if skipped_non_tl:
                            st.caption(f"ℹ️ Ignored {skipped_non_tl} row(s) with a non-{INSTALLER_ID_PREFIX} installer ID.")
                        push_parsed_records_to_installations(parsed, source_label="legacy install(s)")


# ── Persistent Map-sync failure warning (survives the st.rerun() that would ──
# otherwise wipe it — see mirror_records_to_map) ─────────────────────────────
if "map_sync_warning" in st.session_state:
    st.markdown(f'<div class="danger-box">{st.session_state["map_sync_warning"]}</div>', unsafe_allow_html=True)
    if st.button("✅ Got it, dismiss", key="dismiss_map_sync_warning"):
        del st.session_state["map_sync_warning"]
        st.rerun()
    st.divider()


# ── Pending double-count confirmation banner (rendered before the tabs so ──
# it's visible no matter which tab triggered it) ────────────────────────────
if "pending_push" in st.session_state:
    pend = st.session_state["pending_push"]
    st.markdown("""
    <div class="danger-box">
    ⚠️ <b>Possible double-count risk.</b> The record(s) below already have a manually-entered
    quantity for that date/technician/location with no matching upload history — adding this
    upload on top could count the same real installs twice. Review, then choose:
    </div>
    """, unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(pend["risky"]), use_container_width=True, hide_index=True)
    pc1, pc2 = st.columns(2)
    with pc1:
        if st.button("✅ Proceed Anyway (verified — not duplicates)", type="primary", use_container_width=True, key="pending_push_proceed"):
            records, label = pend["records"], pend["source_label"]
            del st.session_state["pending_push"]
            _execute_push(records, label)
    with pc2:
        if st.button("❌ Cancel This Upload", use_container_width=True, key="pending_push_cancel"):
            del st.session_state["pending_push"]
            st.info("Upload cancelled — nothing was saved.")
            st.rerun()
    st.divider()


# ── Tabs Configuration ────────────────────────────────────────────────────────
tab_dash, tab_analytics, tab_map, tab_inst, tab_inv, tab_admin = st.tabs([
    "📊 Dashboard", "📈 Analytics", "🗺️ Map", "🛠️ Installs", "📦 Store", "⚙️ Admin"
])

# ═══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dash:
    df_inst = df_installations_master
    df_inv = df_inventory_master

    st.markdown('<div class="sec-hdr">📦 Live Inventory Stock</div>', unsafe_allow_html=True)

    if not df_inv.empty and has_col(df_inv, "type", "qty"):
        total_in_1ph = safe_numeric_col(df_inv[df_inv["type"] == "1 PH"], "qty").sum()
        total_in_3ph = safe_numeric_col(df_inv[df_inv["type"] == "3 PH"], "qty").sum()
    else:
        total_in_1ph = total_in_3ph = 0

    if not df_inst.empty and has_col(df_inst, "qty_1ph", "qty_3ph"):
        total_out_1ph = safe_numeric_col(df_inst, "qty_1ph").sum()
        total_out_3ph = safe_numeric_col(df_inst, "qty_3ph").sum()
    else:
        total_out_1ph = total_out_3ph = 0

    pending_1ph = int(total_in_1ph - total_out_1ph)
    pending_3ph = int(total_in_3ph - total_out_3ph)

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Received 1PH", int(total_in_1ph))
    sc2.metric("Received 3PH", int(total_in_3ph))
    sc3.metric("Pending 1PH", pending_1ph, delta="⚠️ Deficit!" if pending_1ph < 0 else None, delta_color="inverse")
    sc4.metric("Pending 3PH", pending_3ph, delta="⚠️ Deficit!" if pending_3ph < 0 else None, delta_color="inverse")

    # ── Monthly Installs Overview ────────────────────────────────────────────
    st.divider()
    st.markdown('<div class="sec-hdr">📅 Monthly Installs Overview</div>', unsafe_allow_html=True)

    if df_inst.empty or not has_col(df_inst, "date", "qty_1ph", "qty_3ph", "location"):
        st.info("No installation data yet.")
    else:
        df_month = df_inst.copy()
        df_month["_date"] = pd.to_datetime(df_month["date"], errors="coerce")
        df_month["qty_1ph"] = safe_numeric_col(df_month, "qty_1ph")
        df_month["qty_3ph"] = safe_numeric_col(df_month, "qty_3ph")

        today = date.today()
        this_month = df_month[(df_month["_date"].dt.month == today.month) & (df_month["_date"].dt.year == today.year)]

        tm1, tm2, tm3 = st.columns(3)
        tm1.metric("This Month — 1PH", int(this_month["qty_1ph"].sum()))
        tm2.metric("This Month — 3PH", int(this_month["qty_3ph"].sum()))
        tm3.metric("This Month — Total", int(this_month["qty_1ph"].sum() + this_month["qty_3ph"].sum()))

        st.markdown('<div class="sub-hdr">💰 This Month — 1PH Billing</div>', unsafe_allow_html=True)
        month_1ph_count = int(this_month["qty_1ph"].sum())
        billing = calculate_1ph_incentive_billing(month_1ph_count)
        tb1, tb2 = st.columns(2)
        tb1.metric("Total Billing (Rs.)", f"{billing['total_cost']:,.0f}")
        tb2.metric("Blended Cost / Install (Rs.)", f"{billing['blended_per_install']:,.2f}" if month_1ph_count > 0 else "—")
        with st.expander("View slab breakdown"):
            st.caption("Progressive slabs. 1PH only.")
            slab_df = pd.DataFrame(billing["slabs"])
            if not slab_df.empty:
                st.dataframe(slab_df, use_container_width=True, hide_index=True)
            cb1, cb2, cb3 = st.columns(3)
            cb1.metric("Base Cost (Rs.)", f"{billing['base_cost']:,.0f}")
            cb2.metric("Tiered Incentive (Rs.)", f"{billing['tier_incentive']:,.0f}")
            cb3.metric("Flat Add-on (Rs.)", f"{billing['flat_addon']:,.0f}")

        st.markdown('<div class="sub-hdr">📍 This Month, By Location</div>', unsafe_allow_html=True)
        if this_month.empty:
            st.info("No installs recorded this month yet.")
        else:
            loc_month = this_month.groupby("location")[["qty_1ph", "qty_3ph"]].sum().reset_index()
            loc_month["Total"] = loc_month["qty_1ph"] + loc_month["qty_3ph"]
            loc_month.columns = ["Location", "1PH", "3PH", "Total"]
            loc_month = loc_month.sort_values("Total", ascending=False)
            st.dataframe(loc_month, use_container_width=True, hide_index=True)
            download_image_button(loc_month, "This_Month_By_Location.png", key="dl_img_loc_month", title="This Month, By Location")

    st.divider()
    st.markdown('<div class="sec-hdr">🔌 Installation Summary (Filterable)</div>', unsafe_allow_html=True)

    if df_inst.empty or not has_col(df_inst, "date", "tech_name", "location", "qty_1ph", "qty_3ph"):
        st.info("No installation data yet. Add entries in the Installs tab.")
    else:
        f1, f2 = st.columns(2)
        with f1:
            date_range = st.date_input("Date Range", [date.today(), date.today()])
        with f2:
            meter_filter = st.multiselect("Meter Type", ["1 PH", "3 PH"], default=["1 PH", "3 PH"])

        loc_list = sorted([l for l in df_inst["location"].unique() if l.strip()])
        tech_list = sorted([t for t in df_inst["tech_name"].unique() if t.strip()])

        f3, f4 = st.columns(2)
        with f3:
            loc_filter = st.multiselect("Locations", loc_list, default=loc_list)
        with f4:
            tech_filter = st.multiselect("Technicians", tech_list, default=tech_list)

        filtered = df_inst.copy()

        if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
            d_start, d_end = date_range[0], date_range[1]
        elif isinstance(date_range, (list, tuple)) and len(date_range) == 1:
            d_start = d_end = date_range[0]
        else:
            d_start = d_end = date_range

        filtered["_date"] = pd.to_datetime(filtered["date"], errors="coerce").dt.date
        filtered = filtered[(filtered["_date"] >= d_start) & (filtered["_date"] <= d_end)]
        if loc_filter:
            filtered = filtered[filtered["location"].isin(loc_filter)]
        if tech_filter:
            filtered = filtered[filtered["tech_name"].isin(tech_filter)]

        filtered["qty_1ph"] = safe_numeric_col(filtered, "qty_1ph")
        filtered["qty_3ph"] = safe_numeric_col(filtered, "qty_3ph")

        show_1ph, show_3ph = "1 PH" in meter_filter, "3 PH" in meter_filter
        sum_1ph = int(filtered["qty_1ph"].sum()) if show_1ph else 0
        sum_3ph = int(filtered["qty_3ph"].sum()) if show_3ph else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Filtered 1PH", sum_1ph)
        m2.metric("Filtered 3PH", sum_3ph)
        m3.metric("Grand Total", sum_1ph + sum_3ph)

        if not filtered.empty:
            st.markdown('<div class="sec-hdr">👷 Technician Breakdown</div>', unsafe_allow_html=True)
            group_df = filtered.groupby(["tech_name", "location"])[["qty_1ph", "qty_3ph"]].sum().reset_index()
            group_df["Total"] = group_df["qty_1ph"] + group_df["qty_3ph"]
            group_df.columns = ["Technician", "Location", "1PH", "3PH", "Total"]
            st.dataframe(
                group_df.style.apply(
                    lambda data: pd.DataFrame(
                        {c: (data["Total"].apply(lambda v: tier_style(v, INSTALLER_TOTAL_RED_MAX, INSTALLER_TOTAL_YELLOW_MIN, INSTALLER_TOTAL_YELLOW_MAX)) if c == "Total" else "") for c in data.columns},
                        index=data.index,
                    ),
                    axis=None,
                ),
                use_container_width=True, hide_index=True, height=dataframe_height(len(group_df)),
            )
            st.caption("🟩 Strong · 🟨 Mid · 🟥 Below target")
            download_image_button(
                group_df, "Technician_Breakdown.png", key="dl_img_group_df",
                color_grid=build_single_col_color_grid(group_df, "Total", lambda v: tier_colors(v, INSTALLER_TOTAL_RED_MAX, INSTALLER_TOTAL_YELLOW_MIN, INSTALLER_TOTAL_YELLOW_MAX)),
                title="Technician Breakdown",
            )

            st.markdown('<div class="sec-hdr">📤 Export & Share</div>', unsafe_allow_html=True)
            export_df = group_df.copy()
            export_df.loc[len(export_df)] = ["---", "---", "---", "---", "---"]
            export_df.loc[len(export_df)] = ["GRAND TOTAL", "", sum_1ph, sum_3ph, sum_1ph + sum_3ph]
            export_df.loc[len(export_df)] = ["PENDING STOCK", "", pending_1ph, pending_3ph, ""]

            csv_data = export_df.to_csv(index=False).encode("utf-8")
            st.download_button("📥 Download CSV Report", data=csv_data, file_name="Installation_Summary.csv", mime="text/csv", use_container_width=True)

            date_str = f"{d_start} to {d_end}" if d_start != d_end else str(d_start)
            wa_loc_df = filtered.groupby("location")[["qty_1ph", "qty_3ph"]].sum().reset_index()

            wa_lines = ["DPR- Touchlight Infra", f"Date: {date_str}\n"]
            for _, row in wa_loc_df.iterrows():
                wa_lines.append(f"{row['location']}:")
                wa_lines.append(f"1PH: {int(row['qty_1ph']) if show_1ph else 0}, 3PH: {int(row['qty_3ph']) if show_3ph else 0}\n")

            wa_lines.append(f"Total 1PH: {sum_1ph} | Total 3PH: {sum_3ph} | Grand Total: {sum_1ph + sum_3ph}")
            wa_lines.append(f"Pending Stock: 1PH: {pending_1ph} | 3PH: {pending_3ph}")

            wa_text = "\n".join(wa_lines)
            wa_url = f"https://wa.me/?text={urllib.parse.quote(wa_text)}"
            st.markdown(f'<a href="{wa_url}" target="_blank" class="wa-btn">💬 Send to WhatsApp</a>', unsafe_allow_html=True)

    st.divider()
    st.markdown('<div class="sec-hdr">📄 Weekly Customer Report</div>', unsafe_allow_html=True)
    st.caption("Quantities by date & section, with a location snippet per section. Pulls from Installs data only.")

    rf1, rf2 = st.columns(2)
    with rf1:
        report_date_range = st.date_input("Date Range", [date.today() - timedelta(days=6), date.today()], key="report_date_range")
    with rf2:
        report_meter_type = st.selectbox("Meter Type", ["All", "1 PH", "3 PH"], key="report_meter_type")

    df_log_for_report = get_data("UploadedInstallLog")
    all_section_codes = sorted(df_log_for_report["sno"].apply(extract_section_code).unique()) if not df_log_for_report.empty and "sno" in df_log_for_report.columns else []
    report_sections = st.multiselect("Sections (all if none picked)", all_section_codes, key="report_sections")

    if not df_log_for_report.empty and "sno" in df_log_for_report.columns:
        codes = df_log_for_report["sno"].apply(extract_section_code)
        unclassified_n = int((codes == "Unclassified").sum())
        if unclassified_n:
            sample = df_log_for_report.loc[codes == "Unclassified", "sno"].astype(str).head(3).tolist()
            st.warning(f"⚠️ {unclassified_n} record(s) have an unreadable Consumer No and can't be assigned a section code. Examples: {', '.join(repr(s) for s in sample)}")

    if st.button("📄 Generate Weekly Report", type="primary", use_container_width=True, key="generate_weekly_report_btn"):
        if isinstance(report_date_range, (list, tuple)) and len(report_date_range) == 2:
            rd_start, rd_end = report_date_range
        elif isinstance(report_date_range, (list, tuple)) and len(report_date_range) == 1:
            rd_start = rd_end = report_date_range[0]
        else:
            rd_start = rd_end = report_date_range
        with st.spinner("Generating report..."):
            pdf_bytes, err = build_weekly_report_pdf(rd_start, rd_end, section_filter=report_sections or None, meter_type_filter=report_meter_type)
        if err:
            st.error(f"❌ {err}")
        else:
            st.session_state["weekly_report_pdf"] = pdf_bytes
            st.session_state["weekly_report_name"] = f"Weekly_Report_{rd_start}_to_{rd_end}.pdf"
            st.success("✅ Report ready below.")

    if "weekly_report_pdf" in st.session_state:
        st.download_button("📥 Download Report (PDF)", data=st.session_state["weekly_report_pdf"],
                            file_name=st.session_state["weekly_report_name"], mime="application/pdf",
                            use_container_width=True, key="download_weekly_report")

# ═══════════════════════════════════════════════════════════════════════════════
#  ANALYTICS  (fully independent of Installations/Inventory/Technicians —
#  purely for live installer-performance tracking on the phone while traveling)
# ═══════════════════════════════════════════════════════════════════════════════
def process_analytics_upload(analytics_file) -> dict:
    """Parses and merges an uploaded Analytics file into AnalyticsRaw. Returns
    {'ok': bool, 'wrote': bool} — 'ok' is False only if the file couldn't be
    read/parsed at all (drives whether the manual retry button gets
    highlighted); 'wrote' is True only if AnalyticsRaw was actually updated
    (drives whether to rerun and refresh the tables below)."""
    try:
        ws = load_first_data_sheet(analytics_file)
    except Exception as e:
        st.error(f"❌ Could not open the file: {e}")
        return {"ok": False, "wrote": False}

    header_row, col_map = find_header_row(ws, ANALYTICS_REQUIRED_HEADERS)
    if header_row is None:
        st.error("❌ Could not find 'Installation Date', 'Installation Time' and 'Installer LoginID' columns in this file.")
        return {"ok": False, "wrote": False}

    optional_map = find_optional_cols(ws, header_row, ["Section", "New Meter Type"] + list(DETAIL_FIELD_HEADERS.values()))
    parsed_records = []
    skipped_non_tl = 0
    for r in range(header_row + 1, ws.max_row + 1):
        raw_installer = ws.cell(row=r, column=col_map["Installer LoginID"]).value
        if raw_installer is None or str(raw_installer).strip() == "":
            continue
        installer_id = str(raw_installer).strip()
        if not is_valid_installer_id(installer_id):
            skipped_non_tl += 1
            continue
        d = normalize_date_val(ws.cell(row=r, column=col_map["Installation Date"]).value)
        t = normalize_time_val(ws.cell(row=r, column=col_map["Installation Time"]).value)
        if d is None or t is None:
            continue
        section_val = ws.cell(row=r, column=optional_map["Section"]).value if "Section" in optional_map else None
        mtype_val = ws.cell(row=r, column=optional_map["New Meter Type"]).value if "New Meter Type" in optional_map else None
        rec = {
            "date": d, "time": t, "installer_id": installer_id,
            "hour": t.split(":")[0],
            "location": str(section_val).strip() if section_val else "",
            "meter_type": str(mtype_val).strip() if mtype_val else "",
        }
        rec.update(extract_detail_fields(ws, r, optional_map))
        parsed_records.append(rec)

    # New/unrecognized Installer LoginIDs — flagged immediately so the
    # supervisor can add them in Admin without waiting to push to Installs.
    unknown_logins = sorted({rec["installer_id"] for rec in parsed_records if rec["installer_id"].lower() not in tech_login_lookup})
    if unknown_logins:
        st.warning(f"⚠️ New/unrecognized Installer LoginID(s) found: {', '.join(unknown_logins)}. Add a technician with this Login ID in Admin \u2192 Technicians so their name maps correctly.")

    if not parsed_records:
        st.warning("⚠️ No valid TL_ installer rows with a date and time were found in this file.")
        return {"ok": True, "wrote": False}

    araw_detail_cols = ["location", "meter_type", "sno", "old_meter_no", "new_meter_no", "lat", "long"]
    df_araw_existing = get_data("AnalyticsRaw")
    if df_araw_existing.empty:
        df_araw_existing = pd.DataFrame(columns=["key", "date", "time", "installer_id", "hour"] + araw_detail_cols)
    for col in araw_detail_cols:
        if col not in df_araw_existing.columns:
            df_araw_existing[col] = ""

    existing_keys = set(df_araw_existing["key"].values) if "key" in df_araw_existing.columns else set()
    key_to_idx = {k: i for i, k in zip(df_araw_existing.index, df_araw_existing["key"].values)} if "key" in df_araw_existing.columns else {}

    new_rows = []
    dup_count = 0
    backfilled_count = 0
    for rec in parsed_records:
        key = f"{rec['date']}||{rec['time']}||{rec['installer_id']}"
        if key in existing_keys:
            idx = key_to_idx[key]
            # Re-uploading an already-recorded row never adds a new install —
            # but if this record is missing any detail field and the new
            # upload has it, fill it in instead of just skipping.
            filled_something = False
            for col in araw_detail_cols:
                new_val = rec.get(col)
                if new_val in (None, ""):
                    continue
                existing_val = str(df_araw_existing.at[idx, col]).strip()
                if not existing_val:
                    df_araw_existing.at[idx, col] = str(new_val)
                    filled_something = True
            if filled_something:
                backfilled_count += 1
            else:
                dup_count += 1
            continue
        existing_keys.add(key)
        new_row = {"key": key, "date": rec["date"], "time": rec["time"], "installer_id": rec["installer_id"], "hour": rec["hour"]}
        for col in araw_detail_cols:
            new_row[col] = rec.get(col, "")
        new_rows.append(new_row)

    if not new_rows and not backfilled_count:
        st.error("❌ All records in this file are already in Analytics (duplicate date/time/installer) with no missing details to fill in. Nothing to update.")
        return {"ok": True, "wrote": False}

    merged = pd.concat([df_araw_existing, pd.DataFrame(new_rows)], ignore_index=True) if new_rows else df_araw_existing
    if safe_update("AnalyticsRaw", merged):
        msg = f"✅ Added {len(new_rows)} new record(s) to Analytics."
        if backfilled_count:
            msg += f" Filled in missing details for {backfilled_count} existing record(s)."
        if dup_count:
            msg += f" Skipped {dup_count} already-complete duplicate(s)."
        if skipped_non_tl:
            msg += f" Ignored {skipped_non_tl} non-TL_ installer row(s)."
        st.success(msg)
        return {"ok": True, "wrote": True}
    return {"ok": False, "wrote": False}


with tab_analytics:
    st.markdown("""
    <div class="info-box">
    📈 Live installer performance. Independent of Installs/Inventory. Re-uploads add new rows only.
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="sec-hdr">⬆️ Upload Progress File</div>', unsafe_allow_html=True)
    analytics_file = st.file_uploader(
        "Upload MDM export (.xlsx) — TL_ logins only. Processes automatically.",
        type=["xlsx"], key="analytics_uploader"
    )

    SLOW_PROCESS_SECONDS = 5

    if analytics_file is not None:
        file_fp = f"{analytics_file.name}_{analytics_file.size}"

        if st.session_state.get("analytics_last_fp") != file_fp:
            t0 = time.time()
            with st.spinner("📊 Processing and adding to Analytics..."):
                result = process_analytics_upload(analytics_file)
            st.session_state["analytics_last_fp"] = file_fp
            st.session_state["analytics_last_ok"] = result["ok"]
            st.session_state["analytics_last_slow"] = (time.time() - t0) > SLOW_PROCESS_SECONDS
            if result["wrote"]:
                st.rerun()

        last_ok = st.session_state.get("analytics_last_ok", True)
        last_slow = st.session_state.get("analytics_last_slow", False)
        needs_attention = (not last_ok) or last_slow

        if needs_attention:
            st.warning(("⚠️ Automatic processing failed — tap below to retry." if not last_ok
                        else "⏳ Automatic processing took a while — tap below if the data below doesn't look up to date."))

        btn_label = "🔁 Retry: Process & Add To Analytics" if not last_ok else "📊 Process & Add To Analytics"
        if st.button(btn_label, type=("primary" if needs_attention else "secondary"), use_container_width=True, key="manual_analytics_process_btn"):
            t0 = time.time()
            with st.spinner("📊 Processing and adding to Analytics..."):
                result = process_analytics_upload(analytics_file)
            st.session_state["analytics_last_fp"] = file_fp
            st.session_state["analytics_last_ok"] = result["ok"]
            st.session_state["analytics_last_slow"] = (time.time() - t0) > SLOW_PROCESS_SECONDS
            if result["wrote"]:
                st.rerun()

    # ── Build analytics tables from stored raw data ─────────────────────────
    st.divider()
    df_araw = get_data("AnalyticsRaw")

    if df_araw.empty or not has_col(df_araw, "date", "time", "installer_id", "hour"):
        st.info("No analytics data yet — upload a progress file above to get started.")
    else:
        avail_dates = sorted(df_araw["date"].unique(), reverse=True)
        sel_date = st.selectbox("Viewing date", avail_dates, index=0)
        day_df = df_araw[df_araw["date"] == sel_date].copy()
        day_df["hour_int"] = pd.to_numeric(day_df["hour"], errors="coerce")
        installers = sorted(day_df["installer_id"].unique())

        st.markdown('<div class="sec-hdr">📌 Today At A Glance</div>', unsafe_allow_html=True)
        forecast_total, trend_multiplier = forecast_total_installs(day_df, installers) if installers else (None, 1.0)
        g1, g2, g3, g4 = st.columns(4)
        with g1:
            render_colored_metric("Total Installs", len(day_df), GRAND_TOTAL_RED_MAX, GRAND_TOTAL_YELLOW_MAX)
        g2.metric("Active Installers", len(installers))
        g3.metric("Avg / Installer", round(len(day_df) / len(installers), 1) if installers else 0)
        with g4:
            if forecast_total is not None:
                render_colored_metric("Forecasted Total", forecast_total, GRAND_TOTAL_RED_MAX, GRAND_TOTAL_YELLOW_MAX)
            else:
                st.metric("Forecasted Total", "—")
        if forecast_total is not None:
            if trend_multiplier < 0.97:
                trend_note = f"⬇️ pace {round((1 - trend_multiplier) * 100)}% below day avg"
            elif trend_multiplier > 1.03:
                trend_note = f"⬆️ pace {round((trend_multiplier - 1) * 100)}% above day avg"
            else:
                trend_note = "➡️ pace steady"
            st.caption(f"Projected to {FORECAST_DAY_END[:5]} · {trend_note}")
        else:
            st.caption(f"Needs an installer with 2+ installs to project.")

        # -- Section-wise summary (combines every section's uploaded file for this date) --
        st.markdown('<div class="sec-hdr">📍 Section-Wise Summary</div>', unsafe_allow_html=True)
        st.caption("All sections uploaded for this date, combined.")
        if has_col(day_df, "location"):
            section_df = day_df.copy()
            section_df["location"] = section_df["location"].replace("", "Unspecified").fillna("Unspecified")
            section_summary = section_df.groupby("location").size().reset_index(name="Installs")
            section_summary.columns = ["Section", "Installs"]
            section_summary = section_summary.sort_values("Installs", ascending=False)
            st.dataframe(section_summary, use_container_width=True, hide_index=True, height=dataframe_height(len(section_summary)))
        else:
            st.info("No Section data on these records yet — re-upload with the Section column present to see this breakdown.")

        # -- Hourly table --------------------------------------------------
        st.markdown('<div class="sec-hdr">⏱️ Installer-Wise Hourly Count</div>', unsafe_allow_html=True)
        if day_df["hour_int"].notna().any():
            hr_min = int(day_df["hour_int"].min())
            hr_max = int(day_df["hour_int"].max())
        else:
            hr_min, hr_max = 8, 18

        hour_cols = list(range(hr_min, hr_max + 1))
        hourly_rows = []
        for inst in installers:
            sub = day_df[day_df["installer_id"] == inst]
            row = {"Installer": inst}
            for h in hour_cols:
                row[f"{h}-{h+1}"] = int((sub["hour_int"] == h).sum())
            row["Total"] = len(sub)
            hourly_rows.append(row)
        hourly_df = pd.DataFrame(hourly_rows).sort_values("Total", ascending=False)
        total_row = {"Installer": "TOTAL"}
        for h in hour_cols:
            total_row[f"{h}-{h+1}"] = int(hourly_df[f"{h}-{h+1}"].sum())
        total_row["Total"] = int(hourly_df["Total"].sum())
        hourly_df = pd.concat([hourly_df, pd.DataFrame([total_row])], ignore_index=True)
        hour_col_labels = [f"{h}-{h+1}" for h in hour_cols]
        hourly_view_mode = st.radio(
            "Hourly table view", ["📋 Table", "🔲 Heatmap (no horizontal scroll)"],
            horizontal=True, key="hourly_view_mode", label_visibility="collapsed",
        )
        if hourly_view_mode.startswith("📋"):
            st.dataframe(style_hourly_table(hourly_df, hour_col_labels), use_container_width=True, hide_index=True, height=dataframe_height(len(hourly_df)))
        else:
            render_hourly_heatmap(hourly_df, hour_col_labels, build_hourly_color_grid(hourly_df, hour_col_labels))
        st.caption("🟩 Strong · 🟨 Mid · 🟥 Below target")
        glance_line = (
            f"Total: {len(day_df)}  |  Active Installers: {len(installers)}  |  "
            f"Avg/Installer: {round(len(day_df) / len(installers), 1) if installers else 0}  |  "
            f"Forecasted Total: {forecast_total if forecast_total is not None else 'N/A'}"
        )
        download_image_button(
            hourly_df, f"Hourly_Count_{sel_date}.png", key="dl_img_hourly",
            color_grid=build_hourly_color_grid(hourly_df, hour_col_labels),
            title=f"Installer-Wise Hourly Count — {sel_date}\n{glance_line}",
        )

        # -- Half-day split --------------------------------------------------
        st.markdown('<div class="sec-hdr">🌓 Half-Day Split (H1: start – 13:30 · H2: 13:30 – end)</div>', unsafe_allow_html=True)
        half_rows = []
        for inst in installers:
            sub = day_df[day_df["installer_id"] == inst]
            h1 = int((sub["time"] <= HALF_DAY_CUTOFF).sum())
            h2 = int((sub["time"] > HALF_DAY_CUTOFF).sum())
            half_rows.append({"Installer": inst, "H1 (Morning)": h1, "H2 (Afternoon)": h2, "Total": h1 + h2})
        half_df = pd.DataFrame(half_rows).sort_values("Total", ascending=False)

        half_total_row = {
            "Installer": "TOTAL",
            "H1 (Morning)": int(half_df["H1 (Morning)"].sum()) if not half_df.empty else 0,
            "H2 (Afternoon)": int(half_df["H2 (Afternoon)"].sum()) if not half_df.empty else 0,
            "Total": int(half_df["Total"].sum()) if not half_df.empty else 0,
        }
        half_display_df = pd.concat([half_df, pd.DataFrame([half_total_row])], ignore_index=True)
        st.dataframe(half_display_df, use_container_width=True, hide_index=True, height=dataframe_height(len(half_display_df)))
        download_image_button(half_display_df, f"Half_Day_Split_{sel_date}.png", key="dl_img_half", title=f"Half-Day Split — {sel_date}")

        # -- Average install time -------------------------------------------
        st.markdown('<div class="sec-hdr">⏳ Average Install Time / Installer</div>', unsafe_allow_html=True)
        st.caption("Avg (min) between consecutive installs.")
        avg_rows = []
        for inst in installers:
            sub = day_df[day_df["installer_id"] == inst].sort_values("time")
            first_t, last_t = sub["time"].iloc[0], sub["time"].iloc[-1]
            n = len(sub)
            span_min = time_to_minutes(last_t) - time_to_minutes(first_t)
            avg_min = round(span_min / n, 1) if n > 0 else 0
            avg_rows.append({
                "Installer": inst, "First Install": first_t, "Last Install": last_t,
                "Total Installs": n, "Avg Time/Install (min)": avg_min,
            })
        avg_df = pd.DataFrame(avg_rows).sort_values("Total Installs", ascending=False)
        st.dataframe(
            _style_map(avg_df.style, avg_time_style, subset=["Avg Time/Install (min)"]),
            use_container_width=True, hide_index=True, height=dataframe_height(len(avg_df)),
        )
        st.caption("🟩 Faster · 🟨 Mid · 🟥 Slower")
        download_image_button(
            avg_df, f"Avg_Install_Time_{sel_date}.png", key="dl_img_avg",
            color_grid=build_single_col_color_grid(avg_df, "Avg Time/Install (min)", avg_time_colors),
            title=f"Average Install Time / Installer — {sel_date}",
        )

        # -- Quick visual ------------------------------------------------------
        st.markdown('<div class="sec-hdr">📊 Total Installs By Installer</div>', unsafe_allow_html=True)
        chart_df = half_df.set_index("Installer")[["Total"]]
        st.bar_chart(chart_df)

        # -- Locked reset --------------------------------------------------
        st.divider()
        with st.expander("🔒 Reset Analytics Data (start a new day)"):
            st.markdown('<div class="danger-box">⚠️ This permanently deletes all Analytics data collected so far. Do this at the end of the day, once you\'re done reviewing.</div>', unsafe_allow_html=True)
            reset_pin = st.text_input("Enter PIN to unlock reset", type="password", key="analytics_reset_pin")
            if reset_pin == PIN_CODE:
                confirm_reset = st.checkbox("I understand this will delete all Analytics data collected so far")
                if st.button("🗑️ Reset Analytics Data", type="primary", disabled=not confirm_reset, use_container_width=True):
                    empty_df = pd.DataFrame(columns=["key", "date", "time", "installer_id", "hour", "location", "meter_type", "sno", "old_meter_no", "new_meter_no", "lat", "long"])
                    if safe_update("AnalyticsRaw", empty_df):
                        st.success("✅ Analytics data cleared. Ready for a new day.")
                        st.rerun()
            elif reset_pin:
                st.error("❌ Incorrect PIN.")

        # -- Push this date's Analytics data into Installations ---------------
        st.markdown('<div class="sec-hdr">📥 Update Installs From Analytics</div>', unsafe_allow_html=True)
        st.markdown("""
        <div class="info-box">
        Pushes this date's records into Installations. Never double-counts. Unmapped login IDs are flagged.
        </div>
        """, unsafe_allow_html=True)

        if not has_col(day_df, "location") or not has_col(day_df, "meter_type") or (day_df["location"].eq("").all() and day_df["meter_type"].eq("").all()):
            st.caption("No Location/Meter Type on these records — will push as 'Unspecified', not counted in 1PH/3PH.")

        if st.button(f"📥 Update Installs For {sel_date}", type="primary", use_container_width=True):
            push_records = []
            for _, r in day_df.iterrows():
                rec = {"date": r["date"], "time": r["time"], "installer_id": r["installer_id"]}
                for col in ["location", "meter_type", "sno", "old_meter_no", "new_meter_no", "lat", "long"]:
                    rec[col] = r[col] if col in day_df.columns else ""
                push_records.append(rec)
            push_parsed_records_to_installations(push_records, source_label="install(s) from Analytics")

# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
#  MAP  (built from MapRecords — its own independent sheet. Populated by a
#  one-way mirror from Installs-tab uploads + Analytics's "Update Installs"
#  push, plus this tab's own Legacy Data upload. Never written back to
#  Installations/UploadedInstallLog.)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_map:
    st.markdown("""
    <div class="info-box">
    🗺️ Installs data mirrors here automatically. The Map-only upload below never affects Installations.
    </div>
    """, unsafe_allow_html=True)

    df_map_raw = get_data("MapRecords")

    if df_map_raw.empty:
        st.info("""
        No records on the Map yet. This is expected if you haven't uploaded anything via the
        Installs tab, Analytics, or the Legacy Data uploader below yet.

        If you *have* uploaded installs and still see this, the most likely cause is that the
        **'MapRecords' worksheet tab doesn't exist yet** in your Google Sheet — the app can't
        create new tabs on its own, it can only write into ones that already exist. Add a tab
        named exactly `MapRecords` (see the app file's setup notes for its columns), then
        re-upload the same file to backfill it.
        """)
    elif not has_col(df_map_raw, "date", "lat", "long"):
        st.warning("⚠️ The 'MapRecords' worksheet is missing expected columns (date/lat/long). Check its header row matches the app's setup notes.")
    else:
        df_map = df_map_raw.copy()
        df_map["_date"] = pd.to_datetime(df_map["date"], errors="coerce").dt.date
        df_map["_lat"] = pd.to_numeric(df_map["lat"], errors="coerce")
        df_map["_long"] = pd.to_numeric(df_map["long"], errors="coerce")

        loc_options = sorted([l for l in df_map["location"].unique() if str(l).strip()]) if "location" in df_map.columns else []
        valid_dates = df_map["_date"].dropna()
        data_min_d, data_max_d = (valid_dates.min(), valid_dates.max()) if not valid_dates.empty else (date.today(), date.today())

        # Default to today when today has data; otherwise start blank so the
        # map isn't silently showing an unrelated historical range.
        today = date.today()
        has_today_data = (not valid_dates.empty) and (today in set(valid_dates))
        default_range = [today, today] if has_today_data else []

        # Give the picker a wide min/max so previous/next month navigation works.
        picker_min = min(data_min_d, today) - timedelta(days=365)
        picker_max = max(data_max_d, today) + timedelta(days=365)

        # Quick presets — the calendar's month arrows can sit off-screen on a
        # narrow phone viewport, so these cover the common jumps without it.
        qp1, qp2, qp3, qp4 = st.columns(4)
        if qp1.button("Today", use_container_width=True, key="map_qp_today"):
            st.session_state["map_date_range"] = (today, today)
            st.rerun()
        if qp2.button("Last 7d", use_container_width=True, key="map_qp_7d"):
            st.session_state["map_date_range"] = (today - timedelta(days=6), today)
            st.rerun()
        if qp3.button("This month", use_container_width=True, key="map_qp_month"):
            st.session_state["map_date_range"] = (today.replace(day=1), today)
            st.rerun()
        if qp4.button("All data", use_container_width=True, key="map_qp_all"):
            st.session_state["map_date_range"] = (data_min_d, data_max_d)
            st.rerun()

        mf1, mf2 = st.columns(2)
        with mf1:
            map_loc_filter = st.multiselect("Section", loc_options, default=loc_options)
        with mf2:
            map_date_range = st.date_input("Date Range", default_range, min_value=picker_min, max_value=picker_max, key="map_date_range")

        if isinstance(map_date_range, (list, tuple)) and len(map_date_range) == 2:
            md_start, md_end = map_date_range[0], map_date_range[1]
        elif isinstance(map_date_range, (list, tuple)) and len(map_date_range) == 1:
            md_start = md_end = map_date_range[0]
        elif isinstance(map_date_range, (list, tuple)):  # empty — nothing picked yet
            md_start = md_end = None
        else:
            md_start = md_end = map_date_range

        if md_start is None:
            st.info("Pick a date range to show pins." + ("" if has_today_data else f" No data for today — data runs {data_min_d} to {data_max_d}."))
            filtered_map = df_map.iloc[0:0]
        else:
            filtered_map = df_map[(df_map["_date"] >= md_start) & (df_map["_date"] <= md_end)]
        if map_loc_filter:
            filtered_map = filtered_map[filtered_map["location"].isin(map_loc_filter)]

        total_in_range = len(filtered_map)
        pinned = filtered_map.dropna(subset=["_lat", "_long"])
        pinned = pinned[(pinned["_lat"] != 0) & (pinned["_long"] != 0)]

        mm1, mm2 = st.columns(2)
        mm1.metric("Records In Filter", total_in_range)
        mm2.metric("With Location Data", len(pinned))

        if pinned.empty:
            st.warning("⚠️ None of the filtered records have latitude/longitude on file.")
        else:
            center_lat, center_lon = pinned["_lat"].mean(), pinned["_long"].mean()
            tooltip_df = pinned.rename(columns={"_lat": "lat", "_long": "lon"})
            for col in ["sno", "old_meter_no", "new_meter_no", "tech_name", "location", "date"]:
                if col not in tooltip_df.columns:
                    tooltip_df[col] = ""

            layer = pdk.Layer(
                "ScatterplotLayer",
                data=tooltip_df,
                get_position=["lon", "lat"],
                get_fill_color=[14, 159, 110, 190],
                get_radius=25,
                radius_min_pixels=4,
                radius_max_pixels=9,
                pickable=True,
                stroked=True,
                get_line_color=[255, 255, 255],
                line_width_min_pixels=1,
            )
            view_state = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=13, pitch=0)
            deck = pdk.Deck(
                layers=[layer],
                initial_view_state=view_state,
                map_style="road",
                tooltip={
                    "html": "<b>SNO:</b> {sno}<br/><b>Section:</b> {location}<br/><b>Date:</b> {date}<br/>"
                            "<b>Installer:</b> {tech_name}<br/><b>Old Meter:</b> {old_meter_no}<br/><b>New Meter:</b> {new_meter_no}",
                    "style": {"backgroundColor": "#10151F", "color": "white", "fontSize": "12px"},
                },
            )
            st.pydeck_chart(deck, use_container_width=True)

            # -- Select a pin: see lat/long as copyable text -----------------
            st.markdown('<div class="sub-hdr">📍 Select A Pin</div>', unsafe_allow_html=True)
            pin_labels = {}
            for idx, r in pinned.reset_index(drop=True).iterrows():
                label = f"{r.get('sno') or r.get('tech_name') or 'Install'} — {r.get('date','')} {r.get('time','')} ({r.get('location','')})"
                pin_labels[label] = idx
            pinned_reset = pinned.reset_index(drop=True)
            sel_pin_label = st.selectbox("Pick a record", ["-- Select --"] + list(pin_labels.keys()), key="map_pin_picker")
            if sel_pin_label != "-- Select --":
                pin_row = pinned_reset.iloc[pin_labels[sel_pin_label]]
                pin_lat, pin_lon = pin_row["_lat"], pin_row["_long"]
                pc1, pc2 = st.columns([2, 1])
                with pc1:
                    st.code(f"{pin_lat}, {pin_lon}", language=None)
                with pc2:
                    st.markdown(
                        f'<a href="https://www.google.com/maps?q={pin_lat},{pin_lon}" target="_blank" class="wa-btn" style="background:#0E9F6E;">📍 Open In Maps</a>',
                        unsafe_allow_html=True,
                    )
                detail_bits = [f"**SNO:** {pin_row.get('sno','—') or '—'}", f"**Installer:** {pin_row.get('tech_name','—') or '—'}",
                               f"**Old Meter:** {pin_row.get('old_meter_no','—') or '—'}", f"**New Meter:** {pin_row.get('new_meter_no','—') or '—'}"]
                st.caption(" · ".join(detail_bits))

            # -- Save view + share ---------------------------------------------
            # Both exports are built on demand: Streamlit re-runs every tab body
            # on each interaction, so generating these eagerly made every click
            # in the app pay for a matplotlib render plus a full KML build.
            st.markdown('<div class="sub-hdr">📤 Export This View</div>', unsafe_allow_html=True)
            filter_desc = f"{', '.join(map_loc_filter) if map_loc_filter and len(map_loc_filter) < len(loc_options) else 'All Sections'} · {md_start} to {md_end}"
            ec1, ec2 = st.columns(2)
            with ec1:
                if st.session_state.get("map_png_ready"):
                    png_snapshot = build_map_snapshot_png(pinned, title=f"Install Locations\n{filter_desc}")
                    st.download_button("📷 Save Map View As PNG", data=png_snapshot, file_name="map_view.png", mime="image/png", use_container_width=True, key="map_png_export")
                elif st.button("📷 Save Map View As PNG", use_container_width=True, key="map_png_prep"):
                    st.session_state["map_png_ready"] = True
                    st.rerun()
                st.caption("Pin positions only (no street basemap).")
            with ec2:
                if st.session_state.get("map_kml_ready"):
                    kml_bytes = build_kml(pinned, doc_name=f"Installed Meters — {filter_desc}")
                    st.download_button("🗺️ Share As KML File", data=kml_bytes, file_name="installed_meters.kml", mime="application/vnd.google-earth.kml+xml", use_container_width=True, key="map_kml_export")
                elif st.button("🗺️ Share As KML File", use_container_width=True, key="map_kml_prep"):
                    st.session_state["map_kml_ready"] = True
                    st.rerun()
                st.caption("Opens in Google Earth, My Maps, or QGIS.")

            with st.expander(f"📋 View {len(pinned)} record(s) as a table"):
                map_table_cols = ["date", "time", "tech_name", "location", "sno", "old_meter_no", "new_meter_no", "lat", "long"]
                map_table_cols = [c for c in map_table_cols if c in pinned.columns]
                st.dataframe(pinned[map_table_cols], use_container_width=True, hide_index=True,
                             height=dataframe_height(len(pinned), max_px=500))

    st.divider()
    with st.expander("📤 Upload Legacy/Historical Data (Map Only — does not affect Installations)"):
        render_map_legacy_upload_widget()

    st.divider()
    st.markdown('<div class="sec-hdr">🧹 Map Data Maintenance</div>', unsafe_allow_html=True)
    with st.expander("🔎 Check & Remove Duplicate Map Records"):
        st.caption("Scoped entirely to Map data — never touches Installations/inventory.")
        if st.button("🔎 Scan For Duplicates", use_container_width=True, key="scan_map_dups_btn"):
            st.session_state["map_dups_scanned"] = True
        if st.session_state.get("map_dups_scanned"):
            map_dups = find_map_duplicates()
            if map_dups.empty:
                st.success("✅ No same-SNO-same-date duplicates found in Map data.")
            else:
                st.warning(f"⚠️ Found {len(map_dups)} record(s) across duplicate SNO+date clusters. Uncheck 'Keep?' to remove — a sensible default (keep earliest, remove the rest) is pre-selected.")
                edited_map_dups = st.data_editor(map_dups, use_container_width=True, hide_index=True, key="map_dups_editor", disabled=[c for c in map_dups.columns if c != "Keep?"])
                to_remove = edited_map_dups[~edited_map_dups["Keep?"]]["Key"].tolist()
                if st.button(f"🗑️ Remove {len(to_remove)} Unchecked Record(s)", type="primary", use_container_width=True, disabled=not to_remove, key="remove_map_dups_btn"):
                    removed = remove_map_records(to_remove)
                    st.success(f"✅ Removed {removed} duplicate record(s) from the Map.")
                    st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
#  INSTALLS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_inst:
    # ── Bulk Upload from MDM Excel export ────────────────────────────────────
    st.markdown('<div class="sec-hdr">📤 Bulk Upload From Excel</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="info-box">
    Upload the daily export instead of entering counts manually. Re-uploads won't double-count.
    </div>
    """, unsafe_allow_html=True)

    bulk_file = st.file_uploader("Upload Installation Excel (.xlsx)", type=["xlsx"], key="bulk_install_uploader")

    if bulk_file is not None:
        if st.button("📥 Process & Save Installs", type="primary", use_container_width=True):
            try:
                ws = load_first_data_sheet(bulk_file)
            except Exception as e:
                st.error(f"❌ Could not open the file: {e}")
                ws = None

            if ws is not None:
                header_row, col_map = find_header_row(ws, INSTALL_BULK_REQUIRED_HEADERS)
                if header_row is None:
                    st.error("❌ Could not find 'Installation Date', 'Installation Time', 'Installer LoginID', 'Section' and 'New Meter Type' columns in this file.")
                else:
                    detail_optional_map = find_optional_cols(ws, header_row, list(DETAIL_FIELD_HEADERS.values()))
                    parsed = []
                    skipped_non_tl = 0
                    for r in range(header_row + 1, ws.max_row + 1):
                        raw_installer = ws.cell(row=r, column=col_map["Installer LoginID"]).value
                        if raw_installer is None or str(raw_installer).strip() == "":
                            continue
                        if not is_valid_installer_id(raw_installer):
                            skipped_non_tl += 1
                            continue
                        d = normalize_date_val(ws.cell(row=r, column=col_map["Installation Date"]).value)
                        t = normalize_time_val(ws.cell(row=r, column=col_map["Installation Time"]).value)
                        if d is None or t is None:
                            continue
                        section = ws.cell(row=r, column=col_map["Section"]).value
                        mtype = ws.cell(row=r, column=col_map["New Meter Type"]).value
                        rec = {
                            "date": d, "time": t,
                            "installer_id": str(raw_installer).strip(),
                            "location": str(section).strip() if section else "Unspecified",
                            "meter_type": str(mtype).strip() if mtype else "",
                        }
                        rec.update(extract_detail_fields(ws, r, detail_optional_map))
                        parsed.append(rec)

                    if not parsed:
                        st.warning(f"⚠️ No valid {INSTALLER_ID_PREFIX} installer rows with a date and time were found in this file.")
                    else:
                        if skipped_non_tl:
                            st.caption(f"ℹ️ Ignored {skipped_non_tl} row(s) with a non-{INSTALLER_ID_PREFIX} installer ID.")
                        push_parsed_records_to_installations(parsed, source_label="install(s)")

    st.divider()
    st.markdown('<div class="sec-hdr">🔍 Search By Meter / Service No</div>', unsafe_allow_html=True)
    st.caption("Check if an SNO was installed by your team.")
    search_query = st.text_input("Search SNO / Old Meter No / New Meter No", key="meter_search_box", placeholder="e.g. 1234567890 or meter serial number")

    if search_query.strip():
        df_search = get_data("UploadedInstallLog")
        if df_search.empty or not has_col(df_search, "sno", "old_meter_no", "new_meter_no"):
            st.info("No install records with meter/SNO details on file yet.")
        else:
            q = search_query.strip().lower()
            for col in ["sno", "old_meter_no", "new_meter_no"]:
                if col not in df_search.columns:
                    df_search[col] = ""
            match_mask = (
                df_search["sno"].str.lower().str.contains(q, na=False) |
                df_search["old_meter_no"].str.lower().str.contains(q, na=False) |
                df_search["new_meter_no"].str.lower().str.contains(q, na=False)
            )
            results = df_search[match_mask]
            if results.empty:
                st.warning(f"⚠️ No matches found for '{search_query.strip()}'.")
            else:
                display_cols_map = {
                    "date": "Date", "installer_id": "Installer LoginID", "location": "Section",
                    "sno": "SNO", "old_meter_no": "Old Meter No", "new_meter_no": "New Meter No",
                    "lat": "Latitude", "long": "Longitude",
                }
                cols_present = [c for c in display_cols_map if c in results.columns]
                results_display = results[cols_present].rename(columns=display_cols_map)
                st.success(f"✅ Found {len(results)} match(es).")
                st.dataframe(results_display, use_container_width=True, hide_index=True,
                             height=dataframe_height(len(results_display), max_px=500))

    with st.expander("📤 Upload Legacy/Historical Data"):
        render_legacy_upload_widget(key_prefix="installs")

    st.divider()
    st.markdown('<div class="sec-hdr">➕ Daily Entry (Add Multiple At Once)</div>', unsafe_allow_html=True)

    if not active_techs or not active_locs:
        st.warning("⚠️ Please add active Technicians and Locations in the **Admin** tab first.")
    else:
        if "installs_batch" not in st.session_state:
            st.session_state["installs_batch"] = []
        if "qm_version" not in st.session_state:
            st.session_state["qm_version"] = 0
        v = st.session_state["qm_version"]

        # ── Quick Add: same day, same location, multiple technicians ────────
        st.markdown('<div class="sub-hdr">⚡ Quick Add — Same Day &amp; Location, Multiple Technicians</div>', unsafe_allow_html=True)
        qc1, qc2 = st.columns(2)
        with qc1:
            qm_date = st.date_input("Date", value=None, key="qm_date")
        with qc2:
            qm_loc = st.selectbox("Location", ["-- Select --"] + active_locs, key="qm_loc")

        qm_techs = st.multiselect("Technicians who worked today", active_techs, key=f"qm_techs_{v}")

        qty_map = {}
        if qm_techs:
            st.caption("Enter quantities for each technician:")
            for t in qm_techs:
                cc1, cc2, cc3 = st.columns([2, 1, 1])
                with cc1:
                    st.markdown(f"**{t}**")
                with cc2:
                    q1 = st.number_input("1PH", min_value=0, step=1, value=0, key=f"qm_q1_{v}_{t}", label_visibility="collapsed")
                with cc3:
                    q3 = st.number_input("3PH", min_value=0, step=1, value=0, key=f"qm_q3_{v}_{t}", label_visibility="collapsed")
                qty_map[t] = (q1, q3)

        if st.button("➕ Add These To Batch", type="primary", use_container_width=True, disabled=not qm_techs):
            if qm_date is None:
                st.error("❌ Pick a date first.")
            elif qm_loc == "-- Select --":
                st.error("❌ Pick a location first.")
            else:
                added = 0
                unmapped_batch = []
                for t, (q1, q3) in qty_map.items():
                    if q1 > 0 or q3 > 0:
                        login_id = name_to_login_id.get(t, "")
                        if not login_id:
                            unmapped_batch.append(t)
                        st.session_state["installs_batch"].append({
                            "date": str(qm_date), "tech_name": t, "installer_id": login_id, "location": qm_loc,
                            "qty_1ph": int(q1), "qty_3ph": int(q3),
                        })
                        added += 1
                if added:
                    st.session_state["qm_version"] += 1
                    st.success(f"✅ Added {added} entr{'y' if added == 1 else 'ies'} to the batch below.")
                    if unmapped_batch:
                        st.warning(f"⚠️ No Login ID on file for: {', '.join(sorted(set(unmapped_batch)))} — add one in Admin so future duplicate checks can match uploads to this technician.")
                    st.rerun()
                else:
                    st.warning("⚠️ Enter at least one quantity for a selected technician.")

        # ── Single one-off entry (different date/location than the above) ───
        with st.expander("➕ Add a single one-off entry (different date or location)"):
            sc1, sc2 = st.columns(2)
            with sc1:
                single_date = st.date_input("Date", value=None, key=f"single_date_{v}")
            with sc2:
                single_tech = st.selectbox("Technician", ["-- Select --"] + active_techs, key=f"single_tech_{v}")
            single_loc = st.selectbox("Location", ["-- Select --"] + active_locs, key=f"single_loc_{v}")
            sc3, sc4 = st.columns(2)
            with sc3:
                single_q1 = st.number_input("1 PH Qty", min_value=0, step=1, value=0, key=f"single_q1_{v}")
            with sc4:
                single_q3 = st.number_input("3 PH Qty", min_value=0, step=1, value=0, key=f"single_q3_{v}")
            if st.button("➕ Add This Entry To Batch", use_container_width=True):
                if single_date is None or single_tech == "-- Select --" or single_loc == "-- Select --":
                    st.error("❌ Fill date, technician and location.")
                elif single_q1 == 0 and single_q3 == 0:
                    st.error("❌ Enter at least one quantity.")
                else:
                    single_login_id = name_to_login_id.get(single_tech, "")
                    st.session_state["installs_batch"].append({
                        "date": str(single_date), "tech_name": single_tech, "installer_id": single_login_id, "location": single_loc,
                        "qty_1ph": int(single_q1), "qty_3ph": int(single_q3),
                    })
                    st.session_state["qm_version"] += 1
                    st.success("✅ Added to batch below.")
                    if not single_login_id:
                        st.warning(f"⚠️ No Login ID on file for {single_tech} — add one in Admin so future duplicate checks can match uploads to this technician.")
                    st.rerun()

        # ── Batch preview cards + Save All ───────────────────────────────────
        st.markdown('<div class="sub-hdr">🧾 Batch Ready To Save</div>', unsafe_allow_html=True)
        batch = st.session_state["installs_batch"]
        if not batch:
            st.info("No entries yet — add some above.")
        else:
            for i, entry in enumerate(batch):
                card_col, del_col = st.columns([5, 1])
                with card_col:
                    st.markdown(f"""
                    <div style="background:#ffffff;border:1px solid #E7E9EE;border-radius:12px;
                        padding:10px 14px;margin-bottom:6px;">
                        <b>{entry['tech_name']}</b> — {entry['location']}<br/>
                        <span style="color:#64748b;font-size:.85rem;">
                            {entry['date']} · 1PH: {entry['qty_1ph']} · 3PH: {entry['qty_3ph']}
                        </span>
                    </div>
                    """, unsafe_allow_html=True)
                with del_col:
                    if st.button("🗑️", key=f"del_installs_batch_{i}"):
                        st.session_state["installs_batch"].pop(i)
                        st.rerun()

            bcol1, bcol2 = st.columns(2)
            with bcol1:
                clear_batch = st.button("🗑️ Clear Batch", use_container_width=True)
            with bcol2:
                save_all = st.button(f"💾 Save All ({len(batch)}) To Sheet", type="primary", use_container_width=True)

            if clear_batch:
                st.session_state["installs_batch"] = []
                st.rerun()

            if save_all:
                df_existing = get_data("Installations")
                df_log_check = get_data("UploadedInstallLog")
                log_has_cols = not df_log_check.empty and has_col(df_log_check, "date", "tech_name", "location")
                new_rows, skipped, upload_overlap_warnings = [], [], []
                for entry in batch:
                    dup = False
                    if not df_existing.empty and has_col(df_existing, "date", "tech_name"):
                        dup = not df_existing[(df_existing["date"] == entry["date"]) & (df_existing["tech_name"] == entry["tech_name"])].empty
                    if dup:
                        skipped.append(f"{entry['tech_name']} ({entry['date']})")
                    else:
                        new_rows.append({
                            "date": entry["date"], "tech_name": entry["tech_name"],
                            "installer_id": entry.get("installer_id", ""), "location": entry["location"],
                            "qty_1ph": str(entry["qty_1ph"]), "qty_3ph": str(entry["qty_3ph"]),
                        })
                        # Reverse of the upload-side check: warn if this exact
                        # date/tech/location already has upload history, since
                        # this manual entry might be re-logging the same installs.
                        if log_has_cols:
                            overlap_mask = (
                                (df_log_check["date"] == entry["date"]) &
                                (df_log_check["tech_name"] == entry["tech_name"]) &
                                (df_log_check["location"] == entry["location"])
                            )
                            if overlap_mask.any():
                                upload_overlap_warnings.append(f"{entry['tech_name']} on {entry['date']} at {entry['location']} ({int(overlap_mask.sum())} upload record(s) already exist)")

                if new_rows:
                    updated = pd.concat([df_existing, pd.DataFrame(new_rows)], ignore_index=True) if not df_existing.empty else pd.DataFrame(new_rows)
                    if safe_update("Installations", updated):
                        st.success(f"✅ Saved {len(new_rows)} entr{'y' if len(new_rows) == 1 else 'ies'}.")
                        if skipped:
                            st.warning(f"⚠️ Skipped (already exists for that tech/date): {', '.join(skipped)}")
                        if upload_overlap_warnings:
                            st.warning("⚠️ Possible double-count: these already have upload-recorded installs for the same date/tech/location — verify this manual entry isn't re-logging them: " + "; ".join(upload_overlap_warnings))
                        st.session_state["installs_batch"] = []
                        st.rerun()
                else:
                    st.error(f"❌ All entries were duplicates (already exist for that tech/date): {', '.join(skipped)}")

    st.markdown('<div class="sec-hdr">📋 Installation Log</div>', unsafe_allow_html=True)
    log_data = get_data("Installations")

    if log_data.empty:
        st.info("No installation entries yet.")
    else:
        log_sorted = log_data.iloc[::-1].reset_index(drop=True)
        ITEMS = 10
        total_pages = max(1, math.ceil(len(log_sorted) / ITEMS))
        page = st.number_input(f"Page (1 – {total_pages})", min_value=1, max_value=total_pages, step=1, value=1)
        s, e = (page - 1) * ITEMS, page * ITEMS
        disp_log = log_sorted.iloc[s:e].copy()
        if has_col(disp_log, "qty_1ph", "qty_3ph"):
            disp_log["qty_1ph"] = disp_log["qty_1ph"].apply(lambda x: safe_int(x))
            disp_log["qty_3ph"] = disp_log["qty_3ph"].apply(lambda x: safe_int(x))
            disp_log["Total"] = disp_log["qty_1ph"] + disp_log["qty_3ph"]
        st.dataframe(disp_log, use_container_width=True, hide_index=True)

        st.caption("Select a record to edit or delete:")
        log_options_map = {}
        for idx, row in log_sorted.iterrows():
            label = f"#{idx+1}  {row['date']} | {row['tech_name']}"
            log_options_map[label] = idx

        target_label = st.selectbox("Select Record", ["-- Select --"] + list(log_options_map.keys()), key="inst_sel")

        if target_label != "-- Select --":
            sel_idx = log_options_map[target_label]
            curr_row = log_sorted.iloc[sel_idx]
            curr_q1 = safe_int(curr_row.get("qty_1ph", 0))
            curr_q3 = safe_int(curr_row.get("qty_3ph", 0))
            curr_loc = curr_row.get("location", "")
            loc_idx = active_locs.index(curr_loc) if curr_loc in active_locs and active_locs else 0

            st.markdown(f'<div class="warn-box">⚠️ Modifying: <b>{curr_row["tech_name"]}</b> on <b>{curr_row["date"]}</b></div>', unsafe_allow_html=True)
            with st.form("edit_log_form"):
                e_loc = st.selectbox("Location", active_locs, index=loc_idx) if active_locs else st.text_input("Location", value=curr_loc)
                ec1, ec2 = st.columns(2)
                with ec1:
                    e_q1 = st.number_input("1 PH Qty", min_value=0, step=1, value=curr_q1)
                with ec2:
                    e_q3 = st.number_input("3 PH Qty", min_value=0, step=1, value=curr_q3)
                btn_update, btn_delete = st.columns(2)
                with btn_update:
                    do_update = st.form_submit_button("✏️ Update", type="primary")
                with btn_delete:
                    do_delete = st.form_submit_button("🗑️ Delete")

            if do_update:
                if e_q1 == 0 and e_q3 == 0:
                    st.error("❌ Both quantities cannot be 0.")
                else:
                    mask = ((log_data["date"] == curr_row["date"]) & (log_data["tech_name"] == curr_row["tech_name"]))
                    log_data.loc[mask, ["location", "qty_1ph", "qty_3ph"]] = [str(e_loc), str(e_q1), str(e_q3)]
                    if safe_update("Installations", log_data):
                        st.success("✅ Entry updated.")
                        st.rerun()

            if do_delete:
                st.session_state["pending_inst_del"] = curr_row["date"] + "||" + curr_row["tech_name"]

        if "pending_inst_del" in st.session_state:
            del_date, del_tech = st.session_state["pending_inst_del"].split("||", 1)
            st.markdown(f'<div class="warn-box">⚠️ Confirm delete for <b>{del_tech}</b> on <b>{del_date}</b>?</div>', unsafe_allow_html=True)
            cy, cn = st.columns(2)
            with cy:
                if st.button("✅ Yes, Delete", key="conf_del_inst"):
                    mask = ((log_data["date"] == del_date) & (log_data["tech_name"] == del_tech))
                    log_data = log_data[~mask]
                    if safe_update("Installations", log_data):
                        del st.session_state["pending_inst_del"]
                        st.success("Deleted.")
                        st.rerun()
            with cn:
                if st.button("❌ Cancel", key="cancel_del_inst"):
                    del st.session_state["pending_inst_del"]
                    st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
#  INVENTORY (STORE)
# ═══════════════════════════════════════════════════════════════════════════════
with tab_inv:
    st.markdown('<div class="sec-hdr">📥 Inward Store Material</div>', unsafe_allow_html=True)
    with st.form("inv_form", clear_on_submit=True):
        iv1, iv2 = st.columns(2)
        with iv1:
            idate = st.date_input("Received Date", date.today())
            itype = st.selectbox("Type", ["1 PH", "3 PH"])
        with iv2:
            iqty = st.number_input("Quantity", min_value=1, step=1, value=1)
            imrn = st.text_input("MRN No.")
        imake = st.selectbox("Make", ["Schneider", "Genus", "Other"])
        iv_sub = st.form_submit_button("📥 Save Stock", type="primary")

    if iv_sub:
        if not imrn.strip():
            st.error("❌ MRN No. is required.")
        else:
            df_inv_exist = get_data("Inventory")
            new_inv = pd.DataFrame([{"date": str(idate), "type": str(itype), "qty": str(iqty), "mrn": imrn.strip(), "make": str(imake)}])
            updated_inv = pd.concat([df_inv_exist, new_inv], ignore_index=True) if not df_inv_exist.empty else new_inv
            if safe_update("Inventory", updated_inv):
                st.success(f"✅ Inwarded {iqty} × {itype} ({imake}) — MRN {imrn.strip()}")
                st.rerun()

    st.markdown('<div class="sec-hdr">📊 Live Stock Summary</div>', unsafe_allow_html=True)
    df_inv_t = get_data("Inventory")
    df_inst_s = df_installations_master

    r_1ph = r_3ph = u_1ph = u_3ph = 0
    if not df_inv_t.empty and has_col(df_inv_t, "type", "qty"):
        r_1ph = int(safe_numeric_col(df_inv_t[df_inv_t["type"] == "1 PH"], "qty").sum())
        r_3ph = int(safe_numeric_col(df_inv_t[df_inv_t["type"] == "3 PH"], "qty").sum())
    if not df_inst_s.empty and has_col(df_inst_s, "qty_1ph", "qty_3ph"):
        u_1ph = int(safe_numeric_col(df_inst_s, "qty_1ph").sum())
        u_3ph = int(safe_numeric_col(df_inst_s, "qty_3ph").sum())

    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("1PH Received", r_1ph)
    sm2.metric("3PH Received", r_3ph)
    sm3.metric("1PH Pending Stock", max(r_1ph - u_1ph, 0))
    sm4.metric("3PH Pending Stock", max(r_3ph - u_3ph, 0))

    st.markdown('<div class="sec-hdr">📋 Inventory Log</div>', unsafe_allow_html=True)
    if df_inv_t.empty:
        st.info("No inventory entries yet.")
    else:
        inv_sorted = df_inv_t.iloc[::-1].reset_index(drop=True)
        inv_exp = inv_sorted.rename(columns={"date": "Date", "type": "Type", "qty": "Qty", "mrn": "MRN No", "make": "Make"})
        st.download_button("⬇ Export Inventory CSV", inv_exp.to_csv(index=False).encode(), "inventory.csv", "text/csv", use_container_width=True)

        ITEMS_INV = 10
        total_inv_p = max(1, math.ceil(len(inv_sorted) / ITEMS_INV))
        inv_page = st.number_input(f"Page (1–{total_inv_p})", min_value=1, max_value=total_inv_p, step=1, value=1, key="inv_page")
        si, ei = (inv_page - 1) * ITEMS_INV, inv_page * ITEMS_INV
        st.dataframe(inv_sorted.iloc[si:ei], use_container_width=True, hide_index=True)

        st.caption("Select an inventory entry to edit or delete:")
        inv_options_map = {}
        for idx, row in inv_sorted.iterrows():
            label = f"#{idx+1}  {row.get('date','')} | {row.get('type','')} | MRN:{row.get('mrn','')}"
            inv_options_map[label] = idx

        inv_target = st.selectbox("Select Inventory Record", ["-- Select --"] + list(inv_options_map.keys()), key="inv_sel")

        if inv_target != "-- Select --":
            inv_idx = inv_options_map[inv_target]
            inv_row = inv_sorted.iloc[inv_idx]

            st.markdown(f'<div class="warn-box">⚠️ Modifying: MRN <b>{inv_row.get("mrn","")}</b> — {inv_row.get("type","")} ({inv_row.get("make","")})</div>', unsafe_allow_html=True)
            with st.form("edit_inv_form"):
                ei1, ei2, ei3 = st.columns(3)
                with ei1:
                    e_qty = st.number_input("Quantity", min_value=1, step=1, value=safe_int(inv_row.get("qty", 1), 1))
                with ei2:
                    e_mrn = st.text_input("MRN No.", value=str(inv_row.get("mrn", "")))
                with ei3:
                    make_opts = ["Schneider", "Genus", "Other"]
                    curr_make = inv_row.get("make", "Schneider")
                    mk_idx = make_opts.index(curr_make) if curr_make in make_opts else 0
                    e_make = st.selectbox("Make", make_opts, index=mk_idx)
                ib1, ib2 = st.columns(2)
                with ib1:
                    inv_do_update = st.form_submit_button("✏️ Update", type="primary")
                with ib2:
                    inv_do_delete = st.form_submit_button("🗑️ Delete")

            if inv_do_update:
                if not e_mrn.strip():
                    st.error("❌ MRN No. cannot be empty.")
                else:
                    orig_df = df_inv_t.copy()
                    orig_inv_idx = len(orig_df) - 1 - inv_idx
                    orig_df.iloc[orig_inv_idx, orig_df.columns.get_loc("qty")] = str(e_qty)
                    orig_df.iloc[orig_inv_idx, orig_df.columns.get_loc("mrn")] = e_mrn.strip()
                    orig_df.iloc[orig_inv_idx, orig_df.columns.get_loc("make")] = e_make
                    if safe_update("Inventory", orig_df):
                        st.success("✅ Inventory entry updated.")
                        st.rerun()

            if inv_do_delete:
                st.session_state["pending_inv_del"] = inv_idx

        if "pending_inv_del" in st.session_state:
            del_inv_idx = st.session_state["pending_inv_del"]
            st.markdown('<div class="warn-box">⚠️ Confirm delete? This will affect stock totals.</div>', unsafe_allow_html=True)
            iy, inv_n = st.columns(2)
            with iy:
                if st.button("✅ Yes, Delete", key="conf_del_inv"):
                    orig_df = df_inv_t.copy()
                    orig_inv_ri = len(orig_df) - 1 - del_inv_idx
                    orig_df = orig_df.drop(index=orig_inv_ri).reset_index(drop=True)
                    if safe_update("Inventory", orig_df):
                        del st.session_state["pending_inv_del"]
                        st.success("Deleted.")
                        st.rerun()
            with inv_n:
                if st.button("❌ Cancel", key="cancel_del_inv"):
                    del st.session_state["pending_inv_del"]
                    st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN
# ═══════════════════════════════════════════════════════════════════════════════
with tab_admin:
    if st.button("🔓 Log Out This Browser", use_container_width=True, key="logout_btn"):
        st.session_state["authenticated"] = False
        if "k" in st.query_params:
            del st.query_params["k"]
        st.components.v1.html("""
        <script>
        try { window.parent.localStorage.removeItem('vja_remember_token'); } catch (e) {}
        </script>
        """, height=0)
        st.rerun()
    st.caption("Forgets this browser only.")

    st.markdown("""
    <div class="warn-box" style="background:#f8f9fa;border-color:#cbd5e1;color:#475569;">
    💡 <b>Tip:</b> Add one or several at once below, review them as cards, then Save Batch.
    Existing entries are listed further down as cards — tap ✏️ Edit to change details or toggle
    Active/Inactive, or 🗑️ to delete.
    </div>
    """, unsafe_allow_html=True)

    subtab_tech, subtab_loc = st.tabs(["👷 Technicians", "📍 Locations"])

    # ── Technicians ───────────────────────────────────────────────────────────
    with subtab_tech:
        if "tech_batch" not in st.session_state:
            st.session_state["tech_batch"] = []
        if "tech_form_version" not in st.session_state:
            st.session_state["tech_form_version"] = 0
        tv = st.session_state["tech_form_version"]

        st.markdown('<div class="sub-hdr">➕ Add Technicians (one or several)</div>', unsafe_allow_html=True)
        st.caption("Login ID (e.g. TL_Vinod) maps uploads to this technician.")
        tc1, tc2, tc3, tc4 = st.columns([2, 1, 1, 1.3])
        with tc1:
            new_t_name = st.text_input("Name", key=f"new_t_name_{tv}")
        with tc2:
            new_t_phone = st.text_input("Phone (optional)", key=f"new_t_phone_{tv}")
        with tc3:
            new_t_aadhar = st.text_input("Aadhar (optional)", key=f"new_t_aadhar_{tv}")
        with tc4:
            new_t_login = st.text_input("Login ID (optional)", key=f"new_t_login_{tv}", placeholder="TL_Vinod")

        if st.button("➕ Add To Batch", key="add_tech_batch_btn", type="primary", use_container_width=True):
            if not new_t_name.strip():
                st.error("❌ Name is required.")
            elif any(b["name"] == new_t_name.strip() for b in st.session_state["tech_batch"]):
                st.error("❌ Already added to this batch.")
            else:
                st.session_state["tech_batch"].append({
                    "name": new_t_name.strip(), "phone": new_t_phone.strip(),
                    "aadhar": new_t_aadhar.strip(), "login_id": new_t_login.strip(),
                })
                st.session_state["tech_form_version"] += 1
                st.rerun()

        if st.session_state["tech_batch"]:
            st.markdown('<div class="sub-hdr">🧾 Batch Ready To Save</div>', unsafe_allow_html=True)
            for i, b in enumerate(st.session_state["tech_batch"]):
                bcard, bdel = st.columns([5, 1])
                with bcard:
                    detail = " · ".join([x for x in [b["phone"], b["aadhar"], b.get("login_id", "")] if x]) or "no phone/aadhar/login given"
                    st.markdown(f"""
                    <div style="background:#ffffff;border:1px solid #E7E9EE;border-radius:12px;padding:10px 14px;margin-bottom:6px;">
                        <b>{b['name']}</b><br/><span style="color:#64748b;font-size:.85rem;">{detail}</span>
                    </div>
                    """, unsafe_allow_html=True)
                with bdel:
                    if st.button("🗑️", key=f"del_tech_batch_{i}"):
                        st.session_state["tech_batch"].pop(i)
                        st.rerun()

            if st.button(f"💾 Save Batch ({len(st.session_state['tech_batch'])})", key="save_tech_batch", type="primary", use_container_width=True):
                df_t_exist = get_data("Technicians")
                existing_names = set(df_t_exist["name"].values) if (not df_t_exist.empty and "name" in df_t_exist.columns) else set()
                new_rows, skipped = [], []
                for b in st.session_state["tech_batch"]:
                    if b["name"] in existing_names:
                        skipped.append(b["name"])
                    else:
                        new_rows.append({"name": b["name"], "phone": b["phone"], "aadhar": b["aadhar"], "is_active": "1", "login_id": b.get("login_id", "")})
                if new_rows:
                    updated = pd.concat([df_t_exist, pd.DataFrame(new_rows)], ignore_index=True) if not df_t_exist.empty else pd.DataFrame(new_rows)
                    if safe_update("Technicians", updated):
                        st.success(f"✅ Added {len(new_rows)} technician(s).")
                        if skipped:
                            st.warning(f"⚠️ Skipped (already exist): {', '.join(skipped)}")
                        st.session_state["tech_batch"] = []
                        st.rerun()
                else:
                    st.error(f"❌ All names already exist: {', '.join(skipped)}")

        st.markdown('<div class="sec-hdr">👷 Existing Technicians</div>', unsafe_allow_html=True)
        df_t = df_technicians_master.copy()
        if not df_t.empty:
            df_t = df_t.rename(columns={c: str(c).strip().lower() for c in df_t.columns})
            for col in ["name", "phone", "aadhar", "is_active", "login_id"]:
                if col not in df_t.columns:
                    df_t[col] = ""

        if df_t.empty:
            st.info("No technicians added yet.")
        else:
            for idx, row in df_t.iterrows():
                is_active = str(row.get("is_active", "1")).strip() in ["1", "1.0", "true", "yes"]
                pill_color = "#0B7A56" if is_active else "#94a3b8"
                pill_bg = "#E6F7F0" if is_active else "#f1f5f9"
                pill_text = "Active" if is_active else "Inactive"

                rc1, rc2 = st.columns([5, 2])
                with rc1:
                    detail = " · ".join([x for x in [str(row.get("phone", "")), str(row.get("aadhar", "")), (f"Login: {row.get('login_id','')}" if str(row.get("login_id","")).strip() else "")] if x]) or "no phone/aadhar/login on file"
                    st.markdown(f"""
                    <div style="background:#ffffff;border:1px solid #E7E9EE;border-radius:12px;padding:10px 14px;margin-bottom:6px;">
                        <b>{row.get('name','')}</b>
                        <span style="background:{pill_bg};color:{pill_color};border-radius:20px;padding:2px 10px;
                            font-size:.72rem;font-weight:700;margin-left:8px;">{pill_text}</span><br/>
                        <span style="color:#64748b;font-size:.85rem;">{detail}</span>
                    </div>
                    """, unsafe_allow_html=True)
                with rc2:
                    ecol, dcol = st.columns(2)
                    with ecol:
                        edit_clicked = st.button("✏️", key=f"edit_tech_{idx}")
                    with dcol:
                        del_clicked = st.button("🗑️", key=f"del_tech_{idx}")

                if edit_clicked:
                    st.session_state["editing_tech_idx"] = idx
                if del_clicked:
                    st.session_state["deleting_tech_idx"] = idx

                if st.session_state.get("editing_tech_idx") == idx:
                    with st.form(f"edit_tech_form_{idx}"):
                        e_name = st.text_input("Name", value=str(row.get("name", "")))
                        e_phone = st.text_input("Phone (optional)", value=str(row.get("phone", "")))
                        e_aadhar = st.text_input("Aadhar (optional)", value=str(row.get("aadhar", "")))
                        e_login = st.text_input("Login ID (optional)", value=str(row.get("login_id", "")), placeholder="TL_Vinod")
                        e_active = st.selectbox("Status", ["Active", "Inactive"], index=0 if is_active else 1)
                        sv, cn = st.columns(2)
                        with sv:
                            do_save = st.form_submit_button("💾 Save", type="primary")
                        with cn:
                            do_cancel = st.form_submit_button("Cancel")
                    if do_save:
                        if not e_name.strip():
                            st.error("❌ Name cannot be empty.")
                        else:
                            df_t.loc[idx, ["name", "phone", "aadhar", "login_id", "is_active"]] = [
                                e_name.strip(), e_phone.strip(), e_aadhar.strip(), e_login.strip(), "1" if e_active == "Active" else "0"
                            ]
                            if safe_update("Technicians", df_t):
                                del st.session_state["editing_tech_idx"]
                                st.success("✅ Updated.")
                                st.rerun()
                    if do_cancel:
                        del st.session_state["editing_tech_idx"]
                        st.rerun()

                if st.session_state.get("deleting_tech_idx") == idx:
                    st.markdown(f'<div class="warn-box">⚠️ Delete <b>{row.get("name","")}</b>? This removes them from future entry forms.</div>', unsafe_allow_html=True)
                    yc, ncol = st.columns(2)
                    with yc:
                        if st.button("✅ Yes, Delete", key=f"conf_del_tech_{idx}"):
                            df_t_new = df_t.drop(index=idx).reset_index(drop=True)
                            if safe_update("Technicians", df_t_new):
                                del st.session_state["deleting_tech_idx"]
                                st.success("Deleted.")
                                st.rerun()
                    with ncol:
                        if st.button("❌ Cancel", key=f"cancel_del_tech_{idx}"):
                            del st.session_state["deleting_tech_idx"]
                            st.rerun()

    # ── Locations ─────────────────────────────────────────────────────────────
    with subtab_loc:
        if "loc_batch" not in st.session_state:
            st.session_state["loc_batch"] = []
        if "loc_form_version" not in st.session_state:
            st.session_state["loc_form_version"] = 0
        lv = st.session_state["loc_form_version"]

        st.markdown('<div class="sub-hdr">➕ Add Locations (one or several)</div>', unsafe_allow_html=True)
        new_loc_name = st.text_input("Location Name", key=f"new_loc_name_{lv}")

        if st.button("➕ Add To Batch", key="add_loc_batch_btn", type="primary", use_container_width=True):
            if not new_loc_name.strip():
                st.error("❌ Location name is required.")
            elif new_loc_name.strip() in st.session_state["loc_batch"]:
                st.error("❌ Already added to this batch.")
            else:
                st.session_state["loc_batch"].append(new_loc_name.strip())
                st.session_state["loc_form_version"] += 1
                st.rerun()

        if st.session_state["loc_batch"]:
            st.markdown('<div class="sub-hdr">🧾 Batch Ready To Save</div>', unsafe_allow_html=True)
            for i, l in enumerate(st.session_state["loc_batch"]):
                bcard, bdel = st.columns([5, 1])
                with bcard:
                    st.markdown(f"""
                    <div style="background:#ffffff;border:1px solid #E7E9EE;border-radius:12px;padding:10px 14px;margin-bottom:6px;">
                        <b>{l}</b>
                    </div>
                    """, unsafe_allow_html=True)
                with bdel:
                    if st.button("🗑️", key=f"del_loc_batch_{i}"):
                        st.session_state["loc_batch"].pop(i)
                        st.rerun()

            if st.button(f"💾 Save Batch ({len(st.session_state['loc_batch'])})", key="save_loc_batch", type="primary", use_container_width=True):
                df_l_exist = get_data("Locations")
                existing_locs = set(df_l_exist["location_name"].values) if (not df_l_exist.empty and "location_name" in df_l_exist.columns) else set()
                new_rows, skipped = [], []
                for l in st.session_state["loc_batch"]:
                    if l in existing_locs:
                        skipped.append(l)
                    else:
                        new_rows.append({"location_name": l})
                if new_rows:
                    updated = pd.concat([df_l_exist, pd.DataFrame(new_rows)], ignore_index=True) if not df_l_exist.empty else pd.DataFrame(new_rows)
                    if safe_update("Locations", updated):
                        st.success(f"✅ Added {len(new_rows)} location(s).")
                        if skipped:
                            st.warning(f"⚠️ Skipped (already exist): {', '.join(skipped)}")
                        st.session_state["loc_batch"] = []
                        st.rerun()
                else:
                    st.error(f"❌ All locations already exist: {', '.join(skipped)}")

        st.markdown('<div class="sec-hdr">📍 Existing Locations</div>', unsafe_allow_html=True)
        df_l = df_locations_master.copy()
        if not df_l.empty:
            df_l = df_l.rename(columns={c: str(c).strip().lower() for c in df_l.columns})
            if "location_name" not in df_l.columns:
                df_l["location_name"] = ""

        if df_l.empty:
            st.info("No locations added yet.")
        else:
            for idx, row in df_l.iterrows():
                rc1, rc2 = st.columns([5, 2])
                with rc1:
                    st.markdown(f"""
                    <div style="background:#ffffff;border:1px solid #E7E9EE;border-radius:12px;padding:10px 14px;margin-bottom:6px;">
                        <b>{row.get('location_name','')}</b>
                    </div>
                    """, unsafe_allow_html=True)
                with rc2:
                    ecol, dcol = st.columns(2)
                    with ecol:
                        edit_loc_clicked = st.button("✏️", key=f"edit_loc_{idx}")
                    with dcol:
                        del_loc_clicked = st.button("🗑️", key=f"del_loc_{idx}")

                if edit_loc_clicked:
                    st.session_state["editing_loc_idx"] = idx
                if del_loc_clicked:
                    st.session_state["deleting_loc_idx"] = idx

                if st.session_state.get("editing_loc_idx") == idx:
                    with st.form(f"edit_loc_form_{idx}"):
                        e_loc_name = st.text_input("Location Name", value=str(row.get("location_name", "")))
                        sv, cn = st.columns(2)
                        with sv:
                            do_save_loc = st.form_submit_button("💾 Save", type="primary")
                        with cn:
                            do_cancel_loc = st.form_submit_button("Cancel")
                    if do_save_loc:
                        if not e_loc_name.strip():
                            st.error("❌ Location name cannot be empty.")
                        else:
                            df_l.loc[idx, "location_name"] = e_loc_name.strip()
                            if safe_update("Locations", df_l):
                                del st.session_state["editing_loc_idx"]
                                st.success("✅ Updated.")
                                st.rerun()
                    if do_cancel_loc:
                        del st.session_state["editing_loc_idx"]
                        st.rerun()

                if st.session_state.get("deleting_loc_idx") == idx:
                    st.markdown(f'<div class="warn-box">⚠️ Delete <b>{row.get("location_name","")}</b>?</div>', unsafe_allow_html=True)
                    yc, ncol = st.columns(2)
                    with yc:
                        if st.button("✅ Yes, Delete", key=f"conf_del_loc_{idx}"):
                            df_l_new = df_l.drop(index=idx).reset_index(drop=True)
                            if safe_update("Locations", df_l_new):
                                del st.session_state["deleting_loc_idx"]
                                st.success("Deleted.")
                                st.rerun()
                    with ncol:
                        if st.button("❌ Cancel", key=f"cancel_del_loc_{idx}"):
                            del st.session_state["deleting_loc_idx"]
                            st.rerun()

    # ── Data Maintenance ──────────────────────────────────────────────────────
    st.divider()
    st.markdown('<div class="sec-hdr">🧹 Data Maintenance</div>', unsafe_allow_html=True)
    with st.expander(f"🔒 Remove Non-{INSTALLER_ID_PREFIX} Installer Records"):
        st.markdown(f"""
        <div class="danger-box">
        ⚠️ Permanently removes any install record whose Installer LoginID doesn't start with
        <b>{INSTALLER_ID_PREFIX}</b> (from records saved before this filter was standardized
        across all uploads). Their 1PH/3PH counts are correctly subtracted back out of the
        Installations totals. This cannot be undone.
        </div>
        """, unsafe_allow_html=True)
        cleanup_pin = st.text_input("Enter PIN to unlock", type="password", key="cleanup_pin")
        if cleanup_pin == PIN_CODE:
            if st.button(f"🧹 Remove All Non-{INSTALLER_ID_PREFIX} Records", type="primary", use_container_width=True, key="run_cleanup_btn"):
                removed_log, removed_araw = cleanup_non_tl_records()
                if removed_log or removed_araw:
                    st.success(f"✅ Removed {removed_log} record(s) from Installs data and {removed_araw} from Analytics data. Installations totals have been corrected.")
                else:
                    st.info(f"No non-{INSTALLER_ID_PREFIX} records found — nothing to remove.")
                st.rerun()
        elif cleanup_pin:
            st.error("❌ Incorrect PIN.")

    with st.expander("🔎 Check For Possible Double-Counted Installs"):
        st.markdown("""
        <div class="info-box">
        Flags any date/technician/location where the Installations total is higher than what's
        derivable purely from uploaded records — a sign that a manual entry may have been added
        on top of installs that were later also uploaded, double-counting them. This is a
        read-only report; nothing is changed automatically. Review each row, then correct it
        manually via the Installation Log in the Installs tab (edit or delete the affected entry).
        </div>
        """, unsafe_allow_html=True)
        if st.button("🔎 Run Discrepancy Check", use_container_width=True, key="run_discrepancy_check"):
            flagged = diagnose_installations_discrepancy()
            if flagged.empty:
                st.success("✅ No discrepancies found — every Installations row with upload history matches its upload-derived count.")
            else:
                st.warning(f"⚠️ Found {len(flagged)} row(s) where the Installations total exceeds what uploads alone account for.")
                st.dataframe(flagged, use_container_width=True, hide_index=True, height=dataframe_height(len(flagged)))
                st.caption("'Implied Manual Qty' = portion not explained by uploads.")
                csv_data = flagged.to_csv(index=False).encode("utf-8")
                st.download_button("📥 Download This Report", data=csv_data, file_name="installations_discrepancy_report.csv", mime="text/csv", use_container_width=True)

    with st.expander("↩️ Undo A Previous Upload"):
        st.markdown("""
        <div class="info-box">
        Re-upload the exact same Excel file you used for a previous upload (e.g. the file you
        once used in the Map tab's legacy uploader, before that was separated from Installations).
        Since each record's key is generated the same way every time from the file's contents,
        this finds exactly which of those records are still sitting in Installs data — then lets
        you remove precisely those, correctly reversing their 1PH/3PH counts.
        </div>
        """, unsafe_allow_html=True)
        undo_pin = st.text_input("Enter PIN to unlock", type="password", key="undo_pin")
        if undo_pin == PIN_CODE:
            undo_file = st.file_uploader("Re-upload the file to undo", type=["xlsx"], key="undo_uploader")
            if undo_file is not None:
                if st.button("🔍 Find Matching Records In Installs Data", use_container_width=True, key="undo_find_btn"):
                    file_keys = find_matching_log_keys_from_file(undo_file)
                    if file_keys is None:
                        st.error("❌ Could not read this file's columns — make sure it's the same export format.")
                    elif not file_keys:
                        st.warning("⚠️ No valid records found in this file.")
                    else:
                        df_log_undo = get_data("UploadedInstallLog")
                        if df_log_undo.empty or "key" not in df_log_undo.columns:
                            st.info("No Installs data on file at all — nothing to undo.")
                        else:
                            matching = df_log_undo[df_log_undo["key"].isin(file_keys)]
                            if matching.empty:
                                st.info("None of this file's records currently exist in Installs data — they may already have been removed, or this file was never merged in.")
                            else:
                                st.session_state["pending_undo_keys"] = set(matching["key"].values)
                                st.warning(f"⚠️ Found {len(matching)} record(s) from this file still in Installs data.")
                                st.dataframe(matching, use_container_width=True, hide_index=True, height=dataframe_height(len(matching)))
            if "pending_undo_keys" in st.session_state:
                if st.button(f"🗑️ Remove These {len(st.session_state['pending_undo_keys'])} Record(s) & Reverse Counts", type="primary", use_container_width=True, key="undo_remove_btn"):
                    removed = remove_install_log_rows(st.session_state["pending_undo_keys"])
                    st.success(f"✅ Removed {removed} record(s) and corrected Installations totals.")
                    del st.session_state["pending_undo_keys"]
                    st.rerun()
        elif undo_pin:
            st.error("❌ Incorrect PIN.")

    with st.expander("🔁 Find & Remove Duplicate Installs (SNO-based)"):
        st.markdown("""
        <div class="info-box">
        Same SNO twice on the same date usually means one install was uploaded twice.
        Scoped to Installs data — for Map-only duplicates use the Map tab.
        </div>
        """, unsafe_allow_html=True)
        if st.button("🔎 Scan For Duplicates", use_container_width=True, key="scan_sno_dups_btn"):
            st.session_state["sno_dups_scanned"] = True
        scanned = st.session_state.get("sno_dups_scanned", False)
        sno_dups = find_sno_duplicates() if scanned else pd.DataFrame()
        if not scanned:
            pass
        elif sno_dups.empty:
            st.success("✅ No same-SNO-same-date duplicates found in Installs data.")
        else:
            st.warning(f"⚠️ Found {len(sno_dups)} record(s) across duplicate SNO+date clusters. Uncheck 'Keep?' to remove — a sensible default (keep earliest, remove the rest) is pre-selected.")
            edited_sno_dups = st.data_editor(sno_dups, use_container_width=True, hide_index=True, key="sno_dups_editor", disabled=[c for c in sno_dups.columns if c != "Keep?"])
            dup_pin = st.text_input("Enter PIN to unlock removal", type="password", key="sno_dup_pin")
            if dup_pin == PIN_CODE:
                to_remove_sno = edited_sno_dups[~edited_sno_dups["Keep?"]]["Key"].tolist()
                if st.button(f"🗑️ Remove {len(to_remove_sno)} Unchecked Record(s) & Reverse Counts", type="primary", use_container_width=True, disabled=not to_remove_sno, key="remove_sno_dups_btn"):
                    removed = remove_install_log_rows(to_remove_sno)
                    st.success(f"✅ Removed {removed} duplicate record(s) and corrected Installations totals.")
                    st.rerun()
            elif dup_pin:
                st.error("❌ Incorrect PIN.")

        near_dups = find_near_time_duplicates() if scanned else pd.DataFrame()
        if not near_dups.empty:
            st.markdown('<div class="sub-hdr">⏱️ Lower-Confidence: Same Installer, Times Within 2 Minutes</div>', unsafe_allow_html=True)
            st.caption("Review carefully — back-to-back installs can be genuine.")
            st.dataframe(near_dups, use_container_width=True, hide_index=True, height=dataframe_height(len(near_dups)))
