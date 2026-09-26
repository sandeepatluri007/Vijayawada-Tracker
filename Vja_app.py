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
  Technicians           - name, phone, aadhar, is_active, login_id, supervisor
  Locations             - location_name
  Supervisors           - supervisor_id, name, phone, is_active
  Settings              - key, value   (holds monthly_install_target)
  Expenses              - expense_id, month, cost_type, category, item, vehicle_reg,
                           amount, rate_1ph, rate_3ph, recurring
                           (Expenses tab: fixed monthly costs use `amount`; variable
                           per-install costs use `rate_1ph` / `rate_3ph`)
  Vehicles              - reg_no, description, is_active
                           (Technicians.supervisor holds the supervisor_id)
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
import base64
from PIL import Image
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

# ── Messages that survive st.rerun() ──────────────────────────────────────────
# st.rerun() discards everything drawn in the current run, so a confirmation
# like "✅ Added 150 records" followed by a rerun was wiped before anyone could
# read it. With counts also looking unchanged, every action seemed to do
# nothing — prompting repeat clicks. Rather than edit ~28 call sites, success/
# info/warning calls made during a run are remembered, and if that run ends in
# st.rerun() they are replayed once at the top of the next run.
#
# The originals are captured ONCE on the streamlit module: this script
# re-executes on every run, and re-capturing each time would wrap the
# already-wrapped functions, nesting deeper on every rerun.
if not hasattr(st, "_tlis_originals"):
    st._tlis_originals = {n: getattr(st, n) for n in ("success", "info", "warning", "rerun")}
_ST = st._tlis_originals
_RUN_MESSAGES = []   # re-created on every run, since the script re-executes


def _remembering(kind):
    def _show(body, *args, **kwargs):
        _RUN_MESSAGES.append((kind, body))
        return _ST[kind](body, *args, **kwargs)
    return _show


def _rerun_keeping_messages(*args, **kwargs):
    if _RUN_MESSAGES:
        st.session_state["_carry_messages"] = list(_RUN_MESSAGES)
    return _ST["rerun"](*args, **kwargs)


st.success = _remembering("success")
st.info = _remembering("info")
st.warning = _remembering("warning")
st.rerun = _rerun_keeping_messages


def replay_carried_messages():
    """Show, once, whatever the previous run said just before it reran."""
    for kind, body in st.session_state.pop("_carry_messages", []):
        _ST[kind](body)   # the original: replaying must not re-queue itself


# ── Constants ─────────────────────────────────────────────────────────────────
# ── Brand ──────────────────────────────────────────────────────────────────
# Logo embedded as base64 so there's no extra file to deploy alongside the app
# (one less thing to go missing on Streamlit Cloud). LOGO_PRINT_B64 is the
# flattened white-background copy used inside generated PDFs.
LOGO_B64 = "iVBORw0KGgoAAAANSUhEUgAAAGsAAABgCAYAAAAaeIzPAAAs90lEQVR42u19eXxcxZXud07V7VWr5QXvxixmsdnkBQzEMgaDE7OEQWLmQUKA4AwkwJCQhVVSmBBmAnmByUYCA0mGQCSYQAKBYPKTgknCYoHBLPJuvMm2rH3r5Vad98e9t7slS7ZkyHvJPBW/Nm139+3uOnXO+c53vqoGDjJEhBYtWqQBaAx/6EWLFunKykrG6PjYBg31QE1NjaqoqDCZJxLBWstbt24d/+STT4497rjjPtnU1CREROFwOP3MM888dfPNN6fmz5/fxcw9IpJ5aWVlpaqqqjJEJKNT/jEaq7Kykqurqy0AFBQUYPXq1QWPPPLIlxobG8/at2/fCbFYbFwqlUJeXh6YOTAiUqkUjDEQkZSIrJo8efLTl1xyyW8qKiq2JRKJQRfA6PgIxqqsrNTV1dVuQUEBfvzjH19SV1d3+6ZNm453HEdPmTKlcdy4cb8sKytbv3Dhwrfz8/PzAOQBsAB6e3t7JzY0NOS9+eabJ27evHn52rVrpyul8iKRyJ8uvfTSX15++eU/I6Ke8vJyVVtbO2qwj2gsBmAbGhqOvP32278XDoc/NXbs2M1Lly69s7y8/NW1a9eOv/POO482xly+adOm8LHHHntmJBIBAHR0dPStW7fu9eOPP96Nx+Mv3XjjjW/Pmzfv7eeee+6Empqab3Z2ds4jonW33HLLVfPnz//zokWL9B//+Ed3dPoPwViVlZV8zz332EceeeSa73znO/dOmDAhffvtt994+umnP3/XXXfdtHLlys9Fo9EpRJSeMGHCxjlz5tCWLVseI6K9SiluampS1trDS0pKPrV+/fqxjuOMBdA7e/bsf/vud7/7w3Xr1i352te+dndra+vMpUuX/sOdd97536MedgijsrJSA8BTTz11zic/+Un54he/+HpJSQmeeuqpU5cuXdp6/vnny0033fTEq6++epGIFEUiEYRCoUGvFYlEICLqrbfeOv2666770QUXXCBnnnlm509/+tPzRERfd911vznhhBPkvvvu+zQRYRQtHoJ3iciYM888c2dFRcWbIhK57bbbzj711FPlnHPO+XVfX98RzP3mlAGwD80zNx/a8wDYf8Lll1/+wpIlS+QXv/jFjVprXHTRRa8sWbIkJSL5QWkwaoIRjNtuu+3apUuXyiuvvDJXRPIuuOACe+65576Un5+fqZtqamrUcCZWREhEuLy8POT/fer111//2rJlyxKbNm2asGrVqpmzZ8/uuvXWW78NAH4NNzqGOwoKCu5cvnz53vz8fNx1111Xnn322fLOO++UAsCDDz7oHOp1a2pqQgCwY8eOWQsWLEh//etfv5aZsXz58qZly5bVExFGWGz/fz0YABzHiWzYsGFdV1eX+vDDDwu11mbOnDm7y8vL1YoVKw4ZBLz33ntueXm5mjx58sZkMpnSWs82xnBJSYlqb2/v9Y01OkZirI6Ojq6JEyeekpeXZ84666y/dHd3q6qqqstqa2sNER0SbVRZWcmvvfaaU1tbax5++OHblVKxlpaWh6LRqN2wYQOi0SjlsByjY7ijsLDwy8XFxfK9733vahEJl5eXP3fiiSfKI488cl44HA6epiorK3VdXZ3281K/GwCqqalRPthQAMDMePnll887/fTT5ZJLLnmFiPDAAw9cXFJSYpctW1Yb5MNRC4xgFBcXf3nq1Kkyf/781K9//etSEclfvnz5cyeddJJccsklP+rt7Z0WFMDDGVpriMika6+99rsLFy6U888//y0R0du2bVu0aNGi3smTJ8sFF1zw5KixDqEojsfj35w/f/5yrXX7+++/P+eLX/ziFbfccsvq++67767nn39+hYiAiP57/PjxtV/60pfchQsXvgAgFQDA4DobNmwoe+yxx8Y2NjZetnv37k9qrTFlypQ7H3300XueffbZim9961v/NWPGjJ35+flt69at27Fq1aplIqIBjLIZwzXW+PHjvx2NRudt3bp1+dVXX71648aNxx922GErf/WrX30OgHz729/+5zfffPOqRCIxJRaLYd++fQiFQigqKgIRobOzE93d3Rg3bhySySRCoVBbaWlpzS233PJdAHT55Zff3dTUdHFRUdH7Tz31VPk111zzm02bNm2pr68/Z9RYwx8aAIwxNh6Px4koISIL77777iufffbZO+bMmbOzoKDghXPPPfeh2traBQBmNjY2Hv3WW28d0dDQgL1796p0Oo0jjjjCHn/88XTyySe3zJs37xUAiccff3z2woUL74hGo5cbY7B8+fJ7b7755lsdx0l//vOfjxtjRqmmQ/GskpKSb40dO3ZRY2PjmT6cFhEp+MY3vnHDtm3bvtrZ2VnQ0dGB/Pz81paWlmdO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"
LOGO_PRINT_B64 = "iVBORw0KGgoAAAANSUhEUgAAAIYAAAB4CAIAAAC4gx2vAAArdElEQVR42u29eZRe1XUn+tv73PtNNUtVmifEJAZj4xXAxoBjOs96jbGxeW0nuLPS0DybZy/n5dl+HWd18kzyPHstzyFuY6eh4yQPkhA7dJzGgY4xbQYDjQ0CmUFIQkhIKpVKNX/DvWf/3h/n3ltflWqSRF7jt+qsWlqlr747nX329Nu/fa6QxBIG2wYAERGR9j9J28DyOIUhC4uEpJmJiKou8YwkvfequvRDlseSRGJmJJ1z4b+Tk5N79ux58sknDx48ODg4ODw83Gq1zMw5t3LlylWrVq1ateq8884766yz+vr62sWpqst6c6oiCWoR5vHgwYN333333//93+/YsaPValUqlfXr169bt663t7ezszOO44mJiaGhocHBwX379tXrdVU988wzr7zyyve9731nnXVWccJljTl5kXjvg2bcf//9t9xyy8MPP9zX13fZZZdt3779kksuWbt27QLnGhkZeeyxx+699977779/375955577k033fTe975XVdvFvDyWKpLCbz/99NO/+7u/+8QTT2zfvv0DH/jAZZddFr6wa9euhx56aMeOHUNDQ0ePHm02m0mSdHZ2rlixoru7e9u2bW9+85svvPDC8OVnnnnmO9/5zp133jkwMPC5z33uqquuCpdYlspSRRKiJlX90pe+dPPNN1999dWf+tSnzjzzTACPPvrot771rfvvv39kZGTVqlVr1qw5/fTTV61a1dnZKSITExPDw8N79+7dt2/fkSNH4jh+05vedOONNwYZHDly5FOf+tR3vvOdG2644Wtf+1oURctSWVKAZGZpmpL84Ac/WKlU/vIv/zJI6KGHHrryyisHBgauuuqqW2+99dlnn/Xec/7x0ksv3Xnnndddd93q1asvvPDCv/3bvw2fP/DAA/39/VdffXWj0fDeh8Bhecw3spiV5Cc/+clyufz444+HP/zhH/5hrVa76aabnn/++fYDvPfe+/S40f6dwcHB3/u93+vu7r7hhhvq9XqQ1qpVq6677rricstjXpGE2Xz00UcBfP/73w9K87GPfaxcLv/gBz8oxJCm6cIL3MwKUYVPHnvssYGBgWuvvTZJEpI//elPAdxxxx3LUllEJGF23v3ud19xxRVhsu66664QcZFMkuQkps/Mghh27dpVrVa//OUvh8+vv/76Cy64IE3TZdu1iOEaGxvr6+u79dZbw0q/6KKLbrzxRpKtVutUTh0O//znP79hw4apqSkzu//++6vV6rPPPrusKAsMBVCv1+v1+tatW0VkbGxsz54973jHO049vwvpyNve9rbh4eH9+/eLyJYtW5xzQ0NDy1HVQvMWchFVDcs2iqIoio4dO6aqS0QkF4jlRGR0dNR7Xy6XAQS9ieN4ed4XEYmq1uv1HTt2iEhnZ+dll112yy23FMv8VOQhIl//+te3bdu2bt06kjt37pyamipws+Ux79wNDQ1FUXTBBReEvOGpp56KougjH/lI4RJOyO4Xvp3k1772NQA//OEPgz9/xzveAeCJJ55Y9iWLuPfDhw8H+PYP/uAPwqd/93d/JyLvfe97Dx48GD4J0W1ISmyuMSsCbjQaH/3oRwH8yZ/8Sfjk29/+NoBKpfLYY48ti2QRkRw8eHDVqlUf/vCHReQLX/hCkbqfe+65fX19f/RHf7Rv376ln3FkZOTWW2/dtGnTwMDA3/zN34QP77rrLhH56Ec/umXLlgcffHBZJIuIZHBwsFKpPPzww7fffjuAD33oQ+Pj4yTr9frnPve5zZs39/T0XHXVVV/60pfuu+++l19+eXJystAGM2s0GkNDQ48//vhtt932m7/5m6tXr+7r6/vQhz50+PDhkNl8+tOfBvD7v//74+PjAwMDDz/88LJIFhdJtVr94Q9/SPLuu+/u7+/ftGnTn/3ZnxVf+v73v3/DDTecc84569evX7t27caNG88555xLLrnk0ksvPf/887ds2bJ27dq1a9du3rz53e9+97e//e3h4eFw4D333HPRRRfVarVvfvObQR37+/uXRbLwiKYxYREze+c73/ncc8/dfPPNN91002c+85nrr7/+uuuuu+aaa6655hoAR48effbZZw8cOHDs2LGxsTHvfa1WGxgYWLly5ZlnnnnaaaeFU42Ojt5222233nrrE088cc0119xxxx1bt24tYrDlkGrxiCtoyb333kuy2WwGWe3atesjH/nI6tWru7q6Lrvssk984hPf+9739uzZU3xhFhZ56NChH/3oR5/97Ge3b9/e39/f39///ve//6GHHgpfCDHYwYMHBwYGwofLWrK4loTE0DkXPMTpp5/+jW9847Of/eyPf/zje+6557777vvud787MTFRq9VWrFhRq9VCvWRycjL4kqmpqWq1unLlyosuuui3fuu33v72t/f394cqbzhtUMSC47I85hvRHFUtEedcyCS6urquvvrqq6++GsDg4ODevXtffvnlAwcOjI+PT05OqmoURT09PRs2bNi4ceOGDRs2bNjQXsMP+WYh73Dy5Uk/YZEUCFVR4ArLPNBQLr744oXP6L0Phx8PkYW0ZlkqSxVJMO5zakyxzAuzE3x1Ua5v/3dOvCR8v16vt1qtZbbK4hhXd3f3ypUrH3rooQXWbwiWVNU555yLoij8G35xzgW1mO8MwQw+8sgjzrnNmzcvz/tCIgkw7bXXXnv77bc3Go1i7b+6QV2Q6Fe/+tUrrrhizZo1y8yuRUy/mR08eLCrq+t3fud3Apz1Klb9ChTyi1/8IoCnnnoqAGLLwe7idIi//uu/BlBgXKcumIL4QvK2224DEHL4ZXksLpJimgLGdeONN05MTBSCObnaeyHRVqv18Y9/HMBXvvKVZXmcgEjC7JO877771q1bt2bNmu9+97vt2GIBzgcofpYA2sH59r/eddddZ5111ooVK773ve8ty+OERVJI5dixY7/9279dqVS2bdv2la985aWXXppTD4IM5jRur7zyyi233PLGN76xUqlcf/31ARKexfVaHvON2fFVEQvt3r37m9/85p133jkxMXHeeee95S1vufTSS88+++yBgYHu7u4omoHEjIyMHDlyZPfu3Q8++OCDDz741FNPdXZ2vutd77rpppvOO+88tLG/l8dSOcHHU1LDDE5OTj7wwAP/8A//8JOf/OTw4cPj4+NdXV1dXV29vb21Wi1UDycnJ4eHh0dHR7u6ulavXn355Zdv3779yiuvrNVqmNkasTxOUiTtyV370j506NDevXv37t27f//+oaGhsbGxQJ/o7+/fsGHD1q1bN27cuG7dujkxruXxKoikXWPCzC5xpRcY17Jm/LOIZJbetGO6xyMumNlWujz+2UWyPP6/gx2Xx7JIlseySJZFsjxOZUSvnVvJ6pXA4hHbAlHdksOV12xk+MsacYWblmUt+WcdPzk29OTUlIs8LEtxCFCmZSACU5RTf/WK9atLZQNdLpSgW6NM7xs9coTQiEYQoiKBKpClVgI1uhRnxeUrulfKskgWslkif/vS7j/ev0c6InhlnngWvziB0Cxi98TkaZddtaZUljmAA/zFvhcf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"
COMPANY_NAME = "Touchlight Infra Services"
APP_VERSION = "2026.09.18"  # bump on each deploy; shown in the header to confirm which build is live

PIN_CODE = "1323"

# ── 1PH Incentive Billing (from '1Ph Incentive Tier Calculator.xlsx') ───────
# Progressive slab structure, like a tax bracket: each slab's rate applies
# only to the installs that fall within that band, not the whole total.
# Scoped to 1PH only — the uploaded calculator doesn't cover 3PH, so the
# Dashboard tile is explicitly labeled "1PH Billing" rather than guessing at
# a 3PH rate. Update these constants (and INCENTIVE_TIER_SLABS_1PH) if the
# approved rates change.
# ── Local date ──────────────────────────────────────────────────────────────
# Streamlit Community Cloud runs in UTC, so date.today() on the server lags
# India by 5h30m: from midnight to 05:30 IST it still returns YESTERDAY. That
# made the Map default to a day with no pins, and skewed working-days-left.
from datetime import timezone as _tz
IST = _tz(timedelta(hours=5, minutes=30))


def today_ist() -> date:
    return datetime.now(IST).date()


# ── Monthly install target ─────────────────────────────────────────────────
# The working month runs 3rd to 27th inclusive; the 1st/2nd and 28th-31st are
# not install days, so "days remaining" must never count them or the per-day
# target comes out too low to actually hit.
WORK_DAY_START, WORK_DAY_END = 3, 27
DEFAULT_MONTHLY_TARGET = 5000   # fallback until one is set in Admin


def working_days_in_month(year: int, month: int) -> int:
    import calendar
    last = calendar.monthrange(year, month)[1]
    return max(0, min(WORK_DAY_END, last) - WORK_DAY_START + 1)


def working_days_remaining(today: date, last_install_date=None) -> int:
    """Working days still available to install in.

    Counted from the day AFTER the most recent recorded install, because those
    installs are already in the completed total — counting their day again
    would pair work already done with time still to come and understate the
    per-day rate needed. Falls back to counting today inclusive when the month
    has no installs recorded yet."""
    import calendar
    last = calendar.monthrange(today.year, today.month)[1]
    end = min(WORK_DAY_END, last)

    if last_install_date and last_install_date.year == today.year and last_install_date.month == today.month:
        first_open = last_install_date.day + 1      # that day's work is banked
    else:
        first_open = today.day                      # nothing recorded yet, today is still open

    first_open = max(first_open, WORK_DAY_START)
    if first_open > end:
        return 0
    return end - first_open + 1


def monthly_target_status(installed: int, target: int, today: date, last_install_date=None) -> dict:
    """Progress against target, plus the per-day rate needed to still land it."""
    remaining = max(0, target - installed)
    days_left = working_days_remaining(today, last_install_date)
    total_days = working_days_in_month(today.year, today.month)
    per_day_needed = (remaining / days_left) if days_left > 0 else 0.0
    # The pace originally required, for comparison.
    original_per_day = (target / total_days) if total_days > 0 else 0.0
    return {
        "installed": installed, "target": target, "remaining": remaining,
        "days_left": days_left, "total_days": total_days,
        "per_day_needed": per_day_needed, "original_per_day": original_per_day,
        "pct": (installed / target * 100) if target > 0 else 0.0,
        "on_track": per_day_needed <= original_per_day * 1.05 if target > 0 else True,
    }


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
READ_TTL = 600  # seconds. Every open session re-reads all 11 worksheets once per
# TTL window, so this sets the app's standing call rate: at 90s that was ~15
# read calls/min per session and about 4 open sessions (phones, browser tabs)
# exhausted Google's ~60/min quota — which showed up as "limit reached" and,
# because a rate-limited read then retries with 3s and 6s pauses, as the app
# crawling. At 600s it is ~2/min per session. Writes still invalidate their own
# sheet immediately, so saves appear at once; Refresh reloads everything.
HALF_DAY_CUTOFF = "13:30:00"  # H1 = first install .. 13:30, H2 = 13:30 .. last install
FORECAST_DAY_END = "18:00:00"  # assumed end-of-workday for the forecasted-total projection

# ── Conditional formatting thresholds ────────────────────────────────────────
# Mirrors the colour rules used in the LoginID_Summary sheet of the MDM export.
# Tune these if your team size / daily targets differ.
# Table/PNG conditional-formatting pairs. Inks are the design system's signal
# tokens (success-700 / warning-700 / danger-700) so tables match the rest of
# the UI; literal hex because matplotlib and pandas Styler can't read CSS vars.
# The previous orange pair measured 4.44:1 (below AA) — these all clear it.
CF_GREEN_BG, CF_GREEN_FONT = "#C6EFCE", "#0C6633"
CF_YELLOW_BG, CF_YELLOW_FONT = "#FFEB9C", "#875200"
CF_ORANGE_BG, CF_ORANGE_FONT = "#FFD9B3", "#875200"
CF_RED_BG, CF_RED_FONT = "#FFC7CE", "#A93226"

# Per installer × hour cell (e.g. B3:L13 in the source sheet): <2 red, =2 yellow, >2 green
HOURLY_CELL_THRESHOLD = 2
# Per-installer daily Total column (M3:M13 / Q16:Q26): <10 red, 10-15 neutral, 15-20 yellow, >20 green
INSTALLER_TOTAL_RED_MAX, INSTALLER_TOTAL_YELLOW_MIN, INSTALLER_TOTAL_YELLOW_MAX = 10, 15, 20
# Bottom TOTAL row, per-hour aggregate (B14:L14 / U17:U27): same 4-tier scheme
HOURLY_TOTAL_RED_MAX, HOURLY_TOTAL_YELLOW_MIN, HOURLY_TOTAL_YELLOW_MAX = 10, 15, 20
# Grand total for the day (M14): <150 red, 150-200 yellow, >200 green
GRAND_TOTAL_RED_MAX, GRAND_TOTAL_YELLOW_MAX = 150, 200
# Avg install time in minutes (V32:V42): <20 green (fast), 20-30 yellow, >30 red (slow)
# "Active pace" thresholds, calibrated to the field reality that even the
# slowest installer completes a 1PH install in ~25 min hands-on. Because
# breaks/travel are now excluded from this figure, the old 20/30 bands (which
# were measured against break-inflated numbers) would have shown everyone green.
AVG_TIME_GREEN_MAX, AVG_TIME_YELLOW_MAX = 15, 25

# Any gap longer than this between two consecutive installs is treated as a
# break / travel / waiting, not install work, and is excluded from the
# Avg Time/Install figure. NOT used by the forecast — see forecast_total_installs.
BREAK_GAP_THRESHOLD_MIN = 60


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


def _is_aggregate_row(label) -> bool:
    """True for the grand TOTAL row and for per-supervisor subtotal rows, which
    are team aggregates and so use the 4-tier total thresholds rather than the
    per-installer-hour ones."""
    s = str(label).strip()
    return s.upper() == "TOTAL" or s.startswith("—")


def style_hourly_table(df: pd.DataFrame, hour_cols):
    """Applies the LoginID_Summary-style colouring: per-cell 3-tier for each
    installer's hour buckets, 4-tier for the Total column, and a matching
    4-tier scheme for the bottom aggregate TOTAL row."""
    def styler(data):
        css = pd.DataFrame("", index=data.index, columns=data.columns)
        for i in data.index:
            is_total_row = _is_aggregate_row(data.loc[i, "Installer"])
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
        is_total_row = _is_aggregate_row(df.iloc[i]["Installer"])
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


# ── Table image export ───────────────────────────────────────────────────────
# Landscape, measured layout. Replaces a matplotlib table whose output size,
# margins and proportions changed with every table (it centred the table in a
# fixed figure, then cropped whatever whitespace was left) and was capped in
# portrait. Here every column is sized from its actual text and the whole
# table is scaled to fit one landscape canvas, so every export looks the same.
# Phone held sideways is ~19.5:9 (~2.17:1). A 16:9 canvas is taller than that,
# so it left an empty band under shorter tables and showed letterboxed.
IMG_W, IMG_H_MIN = 1920, 885           # ~2.17:1 — a phone in landscape
IMG_MARGIN = 56
IMG_FONT_MAX, IMG_FONT_MIN = 30, 15     # px; shrinks between these to fit
IMG_INK, IMG_INK_SOFT = (20, 24, 31), (75, 79, 86)          # ink-900, ink-600
IMG_HEAD_BG, IMG_HAIRLINE = (20, 24, 31), (226, 228, 232)
IMG_STRIPE = (246, 247, 249)
IMG_BRAND = (14, 110, 122)                                   # brand-700


def _img_font(size: int, bold: bool = False):
    """DejaVu ships inside matplotlib, which is already a dependency — so the
    same font is available everywhere the app runs, including Streamlit Cloud."""
    from PIL import ImageFont
    import matplotlib, os
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(os.path.join(matplotlib.get_data_path(), "fonts", "ttf", name), size)
    except Exception:
        return ImageFont.load_default(size=size)


def _hex_to_rgb(h):
    h = str(h).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else None


def dataframe_to_png_bytes(df: pd.DataFrame, color_grid=None, title: str = None) -> bytes:
    """Table -> landscape PNG.

    `title` may span lines: the first is the heading, the rest are header
    lines (scope, last install, totals, forecast). Callers keep passing one
    string, so the format is identical across every export in the app."""
    from PIL import Image, ImageDraw

    lines = [l for l in (title or "").split("\n") if l.strip()]
    heading, meta = (lines[0], lines[1:]) if lines else ("", [])
    headers = [str(h) for h in df.columns]
    body = [["" if pd.isna(v) else str(v) for v in row] for row in df.itertuples(index=False)]
    n_rows, n_cols = len(body), len(headers)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))

    def text_w(s, font):
        return probe.textlength(s, font=font)

    def natural_widths(fs):
        """Each column as wide as its widest cell (header included) + padding."""
        fb, fr = _img_font(fs, True), _img_font(fs)
        pad = fs * 1.4
        return [max([text_w(headers[j], fb)] + [text_w(r[j], fr) for r in body]) + pad
                for j in range(n_cols)]

    # Header block height depends on font size too; size it for the chosen fs.
    def header_h(fs):
        return int(fs * 1.9) + len(meta) * int(fs * 1.35) + int(fs * 1.0)

    avail_w = IMG_W - 2 * IMG_MARGIN

    # 1) Largest font whose natural table width fits the landscape width.
    fs = IMG_FONT_MAX
    while fs > IMG_FONT_MIN and sum(natural_widths(fs)) > avail_w:
        fs -= 1
    # 2) Then shrink further, if needed, so all rows fit the landscape height.
    row_h = lambda f: int(f * 2.0)
    while fs > IMG_FONT_MIN and (header_h(fs) + (n_rows + 1) * row_h(fs) + 2 * IMG_MARGIN) > IMG_H_MIN:
        fs -= 1

    widths = natural_widths(fs)
    # Spread leftover width across columns so the table spans the canvas
    # instead of floating in the middle.
    spare = avail_w - sum(widths)
    if spare > 0:
        widths = [w + spare * (w / sum(widths)) for w in widths]
    # At the floor font a very wide table can still overflow: scale to fit.
    elif spare < 0:
        widths = [w * avail_w / sum(widths) for w in widths]

    hh = header_h(fs)
    # Rows stretch to fill the landscape height, so a short table uses the
    # whole canvas instead of leaving an empty band below it. Capped so a
    # 3-row table doesn't get comically tall rows.
    avail_h = IMG_H_MIN - 2 * IMG_MARGIN - hh
    rh = int(min(fs * 2.9, max(row_h(fs), avail_h / (n_rows + 1))))
    table_h = (n_rows + 1) * rh
    # Stays 16:9; only grows taller when rows can't fit even at the floor
    # font, so text never drops below a readable size.
    canvas_h = max(IMG_H_MIN, hh + table_h + 2 * IMG_MARGIN)

    img = Image.new("RGB", (IMG_W, canvas_h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f_title, f_meta = _img_font(int(fs * 1.25), True), _img_font(int(fs * 0.9))
    f_head, f_cell, f_cell_b = _img_font(fs, True), _img_font(fs), _img_font(fs, True)

    # -- Header block --
    y = IMG_MARGIN
    d.text((IMG_MARGIN, y), heading, font=f_title, fill=IMG_INK)
    # Brand logo, top-right, sized to the heading
    try:
        logo = Image.open(io.BytesIO(base64.b64decode(LOGO_PRINT_B64))).convert("RGB")
        lh = int(fs * 2.4)
        logo = logo.resize((int(logo.width * lh / logo.height), lh))
        img.paste(logo, (IMG_W - IMG_MARGIN - logo.width, IMG_MARGIN - int(fs * 0.3)))
    except Exception:
        pass
    y += int(fs * 1.9)
    for m in meta:
        d.text((IMG_MARGIN, y), m, font=f_meta, fill=IMG_INK_SOFT)
        y += int(fs * 1.35)
    y += int(fs * 0.4)
    d.line([(IMG_MARGIN, y), (IMG_W - IMG_MARGIN, y)], fill=IMG_BRAND, width=max(2, fs // 8))
    y += int(fs * 0.6)

    # -- Table --
    x0 = IMG_MARGIN
    xs = [x0]
    for w in widths:
        xs.append(xs[-1] + w)

    def cell_text(x_left, w, top, s, font, fill):
        tw = text_w(s, font)
        # Truncate only if a cell still can't fit after scaling.
        while s and tw > w - fs * 0.6:
            s = s[:-2] + "…"
            tw = text_w(s, font)
        bbox = d.textbbox((0, 0), "Ag", font=font)
        th = bbox[3] - bbox[1]
        d.text((x_left + (w - tw) / 2, top + (rh - th) / 2 - bbox[1]), s, font=font, fill=fill)

    d.rectangle([xs[0], y, xs[-1], y + rh], fill=IMG_HEAD_BG)
    for j, h in enumerate(headers):
        cell_text(xs[j], widths[j], y, h, f_head, (255, 255, 255))
    y += rh

    for i, row in enumerate(body):
        is_agg = row and (row[0].strip().upper() == "TOTAL" or row[0].strip().startswith("—"))
        d.rectangle([xs[0], y, xs[-1], y + rh], fill=IMG_STRIPE if i % 2 else (255, 255, 255))
        for j, val in enumerate(row):
            bg, fg = (None, None)
            if color_grid is not None:
                try:
                    bg, fg = color_grid[i][j]
                except (IndexError, TypeError):
                    pass
            bg_rgb = _hex_to_rgb(bg) if bg else None
            if bg_rgb:
                d.rectangle([xs[j], y, xs[j + 1], y + rh], fill=bg_rgb)
            ink = _hex_to_rgb(fg) if fg else IMG_INK
            bold = bool(fg) or is_agg
            cell_text(xs[j], widths[j], y, val, f_cell_b if bold else f_cell, ink or IMG_INK)
        d.line([(xs[0], y + rh), (xs[-1], y + rh)], fill=IMG_HAIRLINE, width=1)
        y += rh

    for x in xs:   # column rules
        d.line([(x, y - n_rows * rh - rh), (x, y)], fill=IMG_HAIRLINE, width=1)
    d.rectangle([xs[0], y - (n_rows + 1) * rh, xs[-1], y], outline=IMG_HAIRLINE, width=1)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


import threading
_RENDER_LOCK = threading.Lock()   # the Map PNG still uses matplotlib, whose pyplot state isn't thread-safe


def lazy_download_button(label: str, make_bytes, file_name: str, mime: str, key: str):
    """One-click download whose file is only built when clicked.

    Streamlit >= 1.64 accepts a callable for `data`, run on click on a separate
    thread. That replaces the old two-step "prepare, then download" pattern,
    which needed two clicks and — once prepared — rebuilt the file on every
    later interaction. on_click="ignore" stops the download from rerunning
    (and redrawing) the entire app."""
    def _build():
        with _RENDER_LOCK:
            return make_bytes()
    st.download_button(label, data=_build, file_name=file_name, mime=mime,
                       use_container_width=True, key=key, on_click="ignore")


def download_image_button(df: pd.DataFrame, file_name: str, key: str, color_grid=None, title: str = None, label: str = "📷 Download as Image"):
    """Download-as-Image for a table: one click, rendered only on demand."""
    if df.empty:
        return
    # Snapshot the inputs now: this function is called in loops (one block
    # per supervisor), and the render happens later on another thread.
    df_snap, grid_snap, title_snap = df.copy(), color_grid, title
    lazy_download_button(
        label, lambda: dataframe_to_png_bytes(df_snap, color_grid=grid_snap, title=title_snap),
        file_name, "image/png", key,
    )


def build_map_snapshot_png(df: pd.DataFrame, title: str) -> bytes:
    """A positional scatter of the filtered pins (Longitude/Latitude, no
    street/satellite basemap tiles — the app has no mapping API key
    configured) saved as a shareable PNG. This is a plot of the pin
    positions, not a screenshot of the interactive tile map above."""
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    ax.scatter(df["_long"], df["_lat"], s=45, c="#00B4C0", edgecolors="white", linewidths=0.9, zorder=3)
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
# ── Stray pins ─────────────────────────────────────────────────────────────
# A single pin kilometres from the rest (a bad GPS fix, or a meter logged under
# the wrong section) forces any "fit all pins" view to zoom out until every
# real install collapses into one corner. Such pins are kept out of the VIEW —
# never out of the data — and named on the image so they can be checked.
STRAY_PIN_MIN_M = 800   # a pin this close to the group is never called stray


def _dist_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def split_stray_pins(lats, lons):
    """Return a list of booleans, True = stray. Distance from the median point,
    with an IQR fence — robust to the very outliers it's looking for, unlike a
    mean. Needs a handful of pins before it will call anything stray."""
    n = len(lats)
    if n < 5:
        return [False] * n
    mlat, mlon = float(pd.Series(lats).median()), float(pd.Series(lons).median())
    d = pd.Series([_dist_m(la, lo, mlat, mlon) for la, lo in zip(lats, lons)])
    q1, q3 = d.quantile(0.25), d.quantile(0.75)
    fence = max(q3 + 3 * (q3 - q1), STRAY_PIN_MIN_M)
    far = [bool(x > fence) for x in d]
    # Only a FEW isolated pins count as stray. A bigger far-off group is a
    # real second work area (e.g. 12 installs 3 km away) — hiding it would
    # misrepresent the section, so then the view simply shows every pin.
    if sum(far) > max(2, int(n * 0.03)):
        return [False] * n
    return far


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
        # Marker size scales with the canvas. A fixed 6px dot is invisible once
        # a ~1200px composite is shrunk into a ~60mm PDF thumbnail, so size it
        # as a fraction of the image instead, with a floor for tiny crops.
        _span = min(cropped.width, cropped.height)
        r = max(7, int(_span * 0.022))
        outline_w = max(2, r // 3)
        for i, (lat, lon) in enumerate(zip(lats, lons)):
            x, y = _lonlat_to_pixel(lon, lat, zoom)
            x, y = x - origin_x - crop_box[0], y - origin_y - crop_box[1]
            draw.ellipse([x - r, y - r, x + r, y + r], fill="#00B4C0", outline="white", width=outline_w)
            if point_labels and i < len(point_labels) and point_labels[i]:
                draw.text((x + r + 3, y - r), str(point_labels[i]), fill="#14181F")

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
            d2.text((8, 8), title, fill="#14181F", font=font)
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


def _fetch_tile(z: int, x: int, y: int):
    import requests
    from PIL import Image
    try:
        r = requests.get(TILE_URL_TEMPLATE.format(z=z, x=x, y=y), timeout=6,
                         headers={"User-Agent": "SmartMeterFieldTracker/1.0"})
        if r.status_code == 200:
            return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        pass
    return None


def build_map_export_png(pins: pd.DataFrame, heading: str, meta_lines) -> bytes:
    """Map tab export: street map, landscape, same header/logo as the table
    images, framed on the group of installs rather than on every pin.

    Replaces a plain latitude/longitude scatter with no streets, whose frame
    was stretched by any stray pin until the real installs sat in a corner."""
    from PIL import Image, ImageDraw

    lats = pd.to_numeric(pins["_lat"], errors="coerce")
    lons = pd.to_numeric(pins["_long"], errors="coerce")
    ok = lats.notna() & lons.notna()
    pins, lats, lons = pins[ok], lats[ok].tolist(), lons[ok].tolist()
    stray = split_stray_pins(lats, lons)
    keep_lat = [la for la, s in zip(lats, stray) if not s]
    keep_lon = [lo for lo, s in zip(lons, stray) if not s]

    meta = list(meta_lines)
    meta.append(f"{len(keep_lat):,} pin(s) shown")
    if any(stray):
        strays = pins[[bool(s) for s in stray]]
        bits = []
        for _, r in strays.head(3).iterrows():
            sno = clean_id_value(r.get("sno", "")) or "no SNO"
            bits.append(f"SNO {sno} at {float(r['_lat']):.4f}, {float(r['_long']):.4f}")
        more = f" (+{len(strays) - 3} more)" if len(strays) > 3 else ""
        meta.append(f"{len(strays)} pin(s) far from the rest, not shown — check location: " + "; ".join(bits) + more)

    fs = 26
    f_title, f_meta = _img_font(int(fs * 1.25), True), _img_font(int(fs * 0.9))
    map_w = IMG_W - 2 * IMG_MARGIN

    canvas = Image.new("RGB", (IMG_W, IMG_H_MIN), (255, 255, 255))
    d = ImageDraw.Draw(canvas)

    # Wrap header lines to the image width — the stray-pin note can list
    # several SNOs with coordinates and would otherwise run off the edge.
    wrapped = []
    for m in meta:
        words, line = m.split(" "), ""
        for w in words:
            trial = f"{line} {w}".strip()
            if d.textlength(trial, font=f_meta) > map_w and line:
                wrapped.append(line)
                line = w
            else:
                line = trial
        wrapped.append(line)
    meta = wrapped

    # -- Header (identical treatment to the table images) --
    y = IMG_MARGIN
    d.text((IMG_MARGIN, y), heading, font=f_title, fill=IMG_INK)
    try:
        logo = Image.open(io.BytesIO(base64.b64decode(LOGO_PRINT_B64))).convert("RGB")
        lh = int(fs * 2.4)
        logo = logo.resize((int(logo.width * lh / logo.height), lh))
        canvas.paste(logo, (IMG_W - IMG_MARGIN - logo.width, IMG_MARGIN - int(fs * 0.3)))
    except Exception:
        pass
    y += int(fs * 1.9)
    for m in meta:
        d.text((IMG_MARGIN, y), m, font=f_meta, fill=IMG_INK_SOFT)
        y += int(fs * 1.35)
    y += int(fs * 0.4)
    d.line([(IMG_MARGIN, y), (IMG_W - IMG_MARGIN, y)], fill=IMG_BRAND, width=3)
    map_top = y + int(fs * 0.6)
    map_h = IMG_H_MIN - IMG_MARGIN - map_top

    if not keep_lat:
        d.text((IMG_MARGIN, map_top + 20), "No pins with coordinates for this view.", font=f_meta, fill=IMG_INK_SOFT)
        buf = io.BytesIO(); canvas.save(buf, format="PNG", optimize=True); return buf.getvalue()

    # -- Frame: the kept pins, padded, stretched to the map area's shape --
    min_lat, max_lat = min(keep_lat), max(keep_lat)
    min_lon, max_lon = min(keep_lon), max(keep_lon)
    # Highest zoom at which the padded pin box still fits the map area.
    zoom = TILE_MAX_ZOOM
    for z in range(TILE_MAX_ZOOM, 1, -1):
        x1, y1 = _lonlat_to_pixel(min_lon, max_lat, z)
        x2, y2 = _lonlat_to_pixel(max_lon, min_lat, z)
        if (x2 - x1) * 1.25 <= map_w and (y2 - y1) * 1.25 <= map_h:
            zoom = z
            break
    zoom = min(zoom, 18)
    x1, y1 = _lonlat_to_pixel(min_lon, max_lat, zoom)
    x2, y2 = _lonlat_to_pixel(max_lon, min_lat, zoom)
    bw, bh = max(x2 - x1, 1) * 1.25, max(y2 - y1, 1) * 1.25
    # Crop box at this zoom with EXACTLY the map area's aspect, centred on the
    # pins, then scaled up by k (< 2, since the next zoom level didn't fit).
    k = min(map_w / bw, map_h / bh)
    cw, ch = map_w / k, map_h / k
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    left, top = cx - cw / 2, cy - ch / 2

    tx0, ty0 = int(left // TILE_SIZE), int(top // TILE_SIZE)
    tx1, ty1 = int((left + cw) // TILE_SIZE), int((top + ch) // TILE_SIZE)
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * TILE_SIZE, (ty1 - ty0 + 1) * TILE_SIZE), (236, 238, 241))
    got_any = False
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            tile = _fetch_tile(zoom, tx, ty)
            if tile is not None:
                mosaic.paste(tile, ((tx - tx0) * TILE_SIZE, (ty - ty0) * TILE_SIZE))
                got_any = True
    ox, oy = left - tx0 * TILE_SIZE, top - ty0 * TILE_SIZE
    view = mosaic.crop((int(ox), int(oy), int(ox + cw), int(oy + ch))).resize((map_w, map_h))

    vd = ImageDraw.Draw(view)
    r = max(7, int(min(map_w, map_h) * 0.012))
    for la, lo in zip(keep_lat, keep_lon):
        px, py = _lonlat_to_pixel(lo, la, zoom)
        vx, vy = (px - left) * k, (py - top) * k
        vd.ellipse([vx - r, vy - r, vx + r, vy + r], fill=(0, 180, 192), outline=(255, 255, 255), width=max(2, r // 3))

    note = TILE_ATTRIBUTION if got_any else "Street map unavailable — pin positions only"
    nf = _img_font(15)
    nw = vd.textlength(note, font=nf)
    vd.rectangle([map_w - nw - 16, map_h - 26, map_w, map_h], fill=(255, 255, 255))
    vd.text((map_w - nw - 8, map_h - 22), note, font=nf, fill=IMG_INK_SOFT)

    canvas.paste(view, (IMG_MARGIN, map_top))
    d.rectangle([IMG_MARGIN, map_top, IMG_MARGIN + map_w - 1, map_top + map_h - 1], outline=IMG_HAIRLINE, width=1)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


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
        name = clean_id_value(r.get("sno")) or str(r.get("tech_name") or "Install").strip()
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
            ax.text(j, i, str(df.iloc[i][col]), ha="center", va="center", fontsize=9, fontweight="bold", color="#14181F")
    ax.set_xticks(np.arange(-0.5, len(cols_to_plot), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n_rows, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.5)
    ax.tick_params(which="minor", size=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)


# ── TLIS Design System components ──────────────────────────────────────────
# Built to the system's StatTile / TechnicianCard / HeroStat / StatusBadge
# specs. Streamlit's own st.metric and st.dataframe can't express these, so
# they are rendered as HTML against the token variables.

ICON_PATHS = {
    # All drawn on the 24px grid with round caps, per the design system.
    "bolt": '<path d="M13 2 3 14h7l-1 8 10-12h-7l1-8Z"/>',
    "alert": '<path d="M12 3 2 20h20L12 3Z"/><path d="M12 10v4"/><circle cx="12" cy="17" r=".9" fill="currentColor" stroke="none"/>',
    "box": '<path d="M21 8 12 3 3 8v8l9 5 9-5V8Z"/><path d="M3 8l9 5 9-5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "gauge": '<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "upload": '<path d="M12 19V7m0 0-4 4m4-4 4 4"/><path d="M4 21h16"/>',
    "download": '<path d="M12 5v12m0 0 4-4m-4 4-4-4"/><path d="M4 21h16"/>',
    "half": '<circle cx="12" cy="12" r="9"/><path d="M12 3v18"/><path d="M12 3a9 9 0 0 1 0 18" fill="currentColor" stroke="none" opacity=".25"/>',
    "users": '<circle cx="9" cy="8" r="3"/><path d="M2.5 20c0-3.3 2.9-6 6.5-6s6.5 2.7 6.5 6"/><circle cx="17.5" cy="9" r="2.3"/><path d="M15.7 14.3c2.6.5 4.8 2.5 4.8 5.7"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M3 11h18"/>',
    "chart": '<path d="M4 20V10M12 20V4M20 20v-7"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/>',
    "target": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/>',
    "pin": '<path d="M12 21s7-6.2 7-11a7 7 0 1 0-14 0c0 4.8 7 11 7 11Z"/><circle cx="12" cy="10" r="2.4"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    "lock": '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    "broom": '<path d="M4 20 14 10"/><path d="M13 5 19 11"/><path d="m11 13 6-6 3 3-6 6-3-3Z"/>',
    "rupee": '<path d="M7 5h10M7 9h10M15 5c0 4-3.5 4-8 4l8 10"/>',
    "receipt": '<path d="M5 3v18l2.5-1.6L10 21l2-1.6L14 21l2.5-1.6L19 21V3Z"/><path d="M9 8h6M9 12h6"/>',
    "plug": '<path d="M9 3v6M15 3v6"/><path d="M6 9h12v3a6 6 0 0 1-12 0Z"/><path d="M12 18v3"/>',
    "wallet": '<rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 10h18"/><circle cx="16.5" cy="15" r="1.2" fill="currentColor" stroke="none"/><path d="M7 6V4.5A1.5 1.5 0 0 1 8.5 3H17"/>',
    "truck": '<path d="M3 6h11v10H3z"/><path d="M14 9h4l3 3v4h-7"/><circle cx="7" cy="18" r="1.8"/><circle cx="17" cy="18" r="1.8"/>',
}


SEC_ICON_SIZE, SUB_ICON_SIZE = 16, 13


def sec_hdr(icon: str, text: str):
    """Section heading with a line icon. The system uses no emoji as interface
    icons — they render differently on every device."""
    st.markdown(
        f'<div class="sec-hdr">{_icon(icon, "--brand-700", SEC_ICON_SIZE)}'
        f'<span>{text}</span></div>',
        unsafe_allow_html=True,
    )


def sub_hdr(icon: str, text: str):
    st.markdown(
        f'<div class="sub-hdr">{_icon(icon, "--ink-600", SUB_ICON_SIZE)}'
        f'<span>{text}</span></div>',
        unsafe_allow_html=True,
    )


def _icon(name: str, color_var: str, size: int = 14) -> str:
    """Line icon on the 24px grid. The system uses no emoji as interface icons."""
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="var({color_var})" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" width="{size}" height="{size}">'
            f'{ICON_PATHS.get(name, ICON_PATHS["box"])}</svg>')


def tab_action_bar(key: str, show_upload: bool = False):
    """Left-aligned action row at the top of a tab. Refresh sits on every tab;
    the upload action only where it means something (Analytics), since
    st.tabs gives no way to know the active tab from the page header."""
    widths = [1.15, 1.6, 6] if show_upload else [1.15, 7.6]
    cols = st.columns(widths)
    with cols[0]:
        if st.button("Refresh", use_container_width=True, key=f"refresh_{key}",
                     help="Reload data from Google Sheets"):
            st.cache_data.clear()
            st.rerun()
    if show_upload:
        with cols[1]:
            if st.button("Update Installs", use_container_width=True, key=f"push_{key}",
                         help="Push this date's Analytics records into Installations"):
                st.session_state["trigger_analytics_push"] = True


def render_stat_tiles(tiles):
    """StatTile row. tiles = [(icon, value, line1, line2, tone)] where tone is
    'normal' or 'danger'. Four fit across a phone; the two-line label is what
    keeps the tile narrow without dropping the label under the 11px floor."""
    cells = []
    for icon, value, l1, l2, tone in tiles:
        ink = "--danger-700" if tone == "danger" else "--ink-900"
        stroke = "--danger-700" if tone == "danger" else "--brand-500"
        cells.append(
            f'<div style="background:var(--surface-100);border-radius:var(--radius-md);'
            f'padding:10px 8px;display:flex;flex-direction:column;gap:6px;">'
            f'{_icon(icon, stroke)}'
            f'<div style="font-size:18px;font-weight:800;color:var({ink});">{value}</div>'
            f'<div style="font-size:11px;color:var(--ink-600);font-weight:700;line-height:1.15;">{l1}<br/>{l2}</div>'
            f'</div>'
        )
    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat({len(tiles)},minmax(0,1fr));'
        f'gap:var(--space-3);margin-bottom:var(--space-5);">{"".join(cells)}</div>',
        unsafe_allow_html=True,
    )


def render_count_cards(rows, columns: int = 3, total_label: str = None):
    """Compact label + count cards for simple summaries (section totals, month
    by location). Replaces small Excel-style tables that are read to spot the
    biggest and smallest, not to cross-reference."""
    if not rows:
        return
    biggest = max(v for _, v in rows) or 1
    cards = []
    for label, value in rows:
        share = value / biggest * 100
        cards.append(
            f'<div style="background:var(--surface-100);border-radius:var(--radius-md);'
            f'padding:var(--space-4);display:flex;flex-direction:column;gap:6px;">'
            f'<div style="font-size:11px;color:var(--ink-600);font-weight:700;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis;">{label}</div>'
            f'<div style="font-size:18px;font-weight:800;color:var(--ink-900);">{value:,}</div>'
            # A proportion bar instead of a coloured cell: shows relative size
            # without putting text on a tinted background.
            f'<div style="height:4px;border-radius:999px;background:var(--surface-200);overflow:hidden;">'
            f'<div style="width:{share:.0f}%;height:100%;background:var(--brand-500);"></div></div>'
            f'</div>'
        )
    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat({columns},minmax(0,1fr));'
        f'gap:var(--space-3);">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )
    if total_label:
        st.caption(f"{total_label}: {sum(v for _, v in rows):,}")


def _tone_token(value, red_max, yellow_max) -> str:
    if value < red_max:
        return "--danger-700"
    if value <= yellow_max:
        return "--warning-700"
    return "--success-700"


def render_hero_stat(label: str, value, context: str, pct: float):
    """HeroStat — one per screen. The ring is a second reading of the same
    number, never a second metric."""
    pct = max(0.0, min(100.0, float(pct)))
    dash = 113.0
    offset = dash * (1 - pct / 100.0)
    st.markdown(f"""
    <div style="border-radius:var(--radius-lg);padding:var(--space-6);
        background:linear-gradient(135deg,var(--brand-500),var(--brand-700));
        color:var(--on-brand);display:flex;align-items:center;gap:var(--space-5);
        margin-bottom:var(--space-5);">
      <svg viewBox="0 0 44 44" width="52" height="52" style="flex-shrink:0;">
        <circle cx="22" cy="22" r="18" fill="none" stroke="rgba(255,255,255,0.3)" stroke-width="5"/>
        <circle cx="22" cy="22" r="18" fill="none" stroke="#FFFFFF" stroke-width="5"
                stroke-linecap="round" stroke-dasharray="{dash:.0f}" stroke-dashoffset="{offset:.0f}"
                transform="rotate(-90 22 22)"/>
      </svg>
      <div style="display:flex;flex-direction:column;gap:3px;">
        <div style="font-size:11px;font-weight:700;opacity:0.92;letter-spacing:0.3px;">{label}</div>
        <div style="font-size:26px;font-weight:800;letter-spacing:-0.5px;">{value}</div>
        <div style="font-size:11px;font-weight:600;opacity:0.95;">{context}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


def render_technician_cards(rows, red_max, yellow_max, columns: int = 2):
    """TechnicianCard grid. rows = [(name, location, count)].
    Two per row roughly halves scroll depth versus one row each, at the same
    type size — density from arrangement, not from shrinking."""
    if not rows:
        return
    cards = []
    for name, loc, count in rows:
        tone = _tone_token(count, red_max, yellow_max)
        initials = "".join(w[0] for w in str(name).split()[:2]).upper() or "?"
        cards.append(
            f'<div style="background:var(--surface-100);border-radius:var(--radius-md);'
            f'padding:var(--space-4);display:flex;flex-direction:column;gap:var(--space-2);">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;">'
            f'<div style="width:25px;height:25px;border-radius:var(--radius-pill);background:var({tone});'
            f'color:var(--on-brand);font-size:10.5px;font-weight:800;display:flex;align-items:center;'
            f'justify-content:center;">{initials}</div>'
            f'<div style="min-width:34px;text-align:center;padding:3px 10px;border-radius:var(--radius-pill);'
            f'background:var({tone});color:var(--on-brand);font-size:13px;font-weight:800;">{count}</div>'
            f'</div>'
            f'<div style="font-size:13px;font-weight:700;color:var(--ink-900);line-height:1.2;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{name}</div>'
            f'<div style="font-size:11px;color:var(--ink-600);font-weight:600;">{loc}</div>'
            f'</div>'
        )
    st.markdown(
        f'<div style="display:grid;grid-template-columns:repeat({columns},minmax(0,1fr));'
        f'gap:var(--space-3);">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


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
    /* ── TLIS Design System tokens ──────────────────────────────────────
       Names and values come from the design system, not from this file.
       Do not lighten --ink-600: at 8.2:1 it is the lightest grey the system
       permits for text, chosen with headroom because sun glare erodes
       perceived contrast well below what a meter reads indoors. */
    --brand-500: #0EA5A8;
    --brand-700: #0E6E7A;
    --brand-050: #E4F8FA;
    --surface-000: #FAFAFA;
    --surface-100: #FFFFFF;
    --surface-200: #ECEDEF;
    --ink-900: #14181F;
    --ink-600: #4B4F56;
    --hairline: #ECECEE;
    --success-700: #0C6633;
    --warning-700: #875200;
    --danger-700: #A93226;
    --on-brand: #FFFFFF;

    --radius-sm: 8px;
    --radius-md: 13px;
    --radius-lg: 18px;
    --radius-pill: 999px;

    --space-1: 4px;
    --space-2: 7px;
    --space-3: 8px;
    --space-4: 11px;
    --space-5: 14px;
    --space-6: 16px;

    /* Legacy aliases — older rules in this file still reference these.
       Kept pointing at tokens so nothing carries an off-system value. */
    --accent: var(--brand-500);
    --accent-dark: var(--brand-700);
    --accent-soft: var(--brand-050);
    --ink: var(--ink-900);
    --ink-soft: var(--ink-600);
    --bg: var(--surface-000);
    --card-border: var(--hairline);
    --surface: var(--surface-100);
    --stripe: var(--surface-000);
    --radius: var(--radius-md);
    --gap: var(--space-5);
}

html, body, [class*="css"] { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
.stApp { background: var(--bg); color: var(--ink); }
#MainMenu, footer, header { visibility:hidden; }

.top-banner {
    background: var(--surface-100);
    border: 1px solid var(--card-border);
    border-radius: var(--radius-lg);
    padding: var(--space-5) 18px;
    display:flex; align-items:center; gap:12px;
    box-shadow: 0 1px 2px rgba(16,21,31,0.04);
}
.top-banner .icon-badge {
    width:40px; height:40px; border-radius:var(--radius-md); background:var(--accent-soft);
    display:flex; align-items:center; justify-content:center; font-size:1.3rem; flex-shrink:0;
}
.top-banner .t { font-size:1.15rem; font-weight:800; color:var(--ink); letter-spacing:-.2px; margin:0; }
.top-banner .s { font-size:.78rem; color:var(--ink-soft); margin:0; font-weight:500; }

/* Segmented-control style tabs, closer to Groww/Kite bottom-nav feel */
.stTabs [data-baseweb="tab-list"] {
    background:var(--surface-200); border-radius:var(--radius-md); padding:4px; gap:2px;
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
    color:var(--on-brand) !important;
    box-shadow: 0 1px 3px rgba(16,21,31,0.15);
}

[data-testid="stMetric"] {
    background: var(--surface-100);
    border: 1px solid var(--card-border); border-radius:var(--radius-md);
    padding: var(--space-6) var(--space-5) !important;
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
/* The icon now occupies this slot — the old accent bar would double up. */
.sec-hdr svg, .sub-hdr svg { flex-shrink:0; }
.sub-hdr {
    font-size:.85rem; font-weight:700; color:var(--ink-600);
    text-transform:uppercase; letter-spacing:.4px;
    display:flex; align-items:center; gap:7px;
    margin: 1.1rem 0 .5rem;
}

.stButton>button {
    background:var(--surface-100) !important; color:var(--ink) !important;
    border:1px solid var(--card-border) !important; border-radius:10px !important;
    font-weight:600 !important; font-size:.92rem !important;
    padding:10px 18px !important; width:100% !important;
    transition:all .15s;
    box-shadow: 0 1px 2px rgba(16,21,31,0.02);
}
.stButton>button:hover { border-color:var(--accent) !important; color:var(--accent-dark) !important; }

button[data-testid="baseButton-primary"], .stButton>button[type="primary"] {
    /* brand-700, not brand-500: white button LABELS are ~15px, and white on
       brand-500 is only 3.01:1. brand-700 gives 5.95:1. */
    background:var(--brand-700) !important; color:var(--on-brand) !important; border-color:var(--brand-700) !important;
}
button[data-testid="baseButton-primary"]:hover, .stButton>button[type="primary"]:hover {
    background:var(--accent-dark) !important; border-color:var(--accent-dark) !important; color:#fff !important;
}

.stSelectbox>div>div, .stNumberInput>div>div>input,
.stTextInput>div>div>input, .stDateInput>div>div>input, .stMultiSelect>div>div {
    background:var(--surface-100) !important; border:1px solid var(--card-border) !important;
    border-radius:10px !important; color:var(--ink) !important; font-size:.9rem !important;
}

.stForm { background:var(--surface-100) !important; border:1px solid var(--card-border) !important;
    border-radius:14px !important; padding:18px !important; }


.warn-box {
    background:#FFF8E8; border:1px solid #F5D98B; border-radius:var(--radius-md);
    padding:var(--space-4) 15px; color:var(--warning-700); font-size:.85rem; margin-bottom:.8rem; font-weight:600;
}
.info-box {
    background:var(--surface-200); border:1px solid var(--card-border); border-radius:var(--radius-md);
    padding:11px 15px; color:var(--ink-soft); font-size:.85rem; margin-bottom:.8rem; font-weight:500;
}
.danger-box {
    background:#FEF2F2; border:1px solid #FCA5A5; border-radius:var(--radius-md);
    padding:var(--space-4) 15px; color:var(--danger-700); font-size:.85rem; margin-bottom:.8rem; font-weight:600;
}

.wa-btn {
    display:block; text-align:center; background:#25D366; color:#fff !important;
    padding:13px; border-radius:var(--radius-md); text-decoration:none; font-weight:700;
    font-size:1rem; letter-spacing:.2px;
    margin-top:1rem; transition: background 0.2s;
    box-shadow: 0 2px 6px rgba(37,211,102,0.25);
}
.wa-btn:hover { background:#1DA851; }

/* Shared card used for batch previews, technician/location rows, etc.
   (previously repeated as inline styles in five places). */
.item-card {
    background: var(--surface-100);
    border: 1px solid var(--card-border);
    border-radius: var(--radius-md);
    padding: var(--space-4) var(--space-5);
    margin-bottom: 6px;
}

/* Brand header logo */
.top-banner .logo { height:34px; width:auto; display:block; flex-shrink:0; }

/* Uniform table chrome */
[data-testid="stDataFrame"], .stDataFrame {
    border-radius: var(--radius);
    border: 1px solid var(--card-border);
    overflow: hidden;
}

/* Tighten Streamlit's default vertical rhythm — the app was accumulating a
   lot of dead vertical space between blocks, especially on mobile. */
.block-container { padding-top: 1.2rem !important; padding-bottom: 2rem !important; }
[data-testid="stVerticalBlock"] { gap: 0.55rem; }
hr { margin: 0.9rem 0 !important; }
[data-testid="stExpander"] { border-radius: var(--radius); border:1px solid var(--card-border); }

/* Compact Analytics uploader. Scoped by Streamlit's per-key class so the
   other upload boxes (Installs bulk upload, legacy uploads) keep full size. */
.st-key-analytics_uploader [data-testid="stFileUploaderDropzone"] {
    padding: 6px 10px !important;
    min-height: 0 !important;
}
.st-key-analytics_uploader [data-testid="stFileUploaderDropzoneInstructions"] { display: none !important; }
.st-key-analytics_uploader section { padding: 0 !important; }
.st-key-analytics_go button { font-weight: 800 !important; letter-spacing: .5px; }

/* ── Mobile ──────────────────────────────────────────────────────────── */
@media (max-width: 640px) {
    .block-container { padding-left: 0.7rem !important; padding-right: 0.7rem !important; }
    /* 3- and 4-up metric rows get cramped on a phone — shrink the type so
       values stay readable instead of wrapping mid-number. */
    [data-testid="stMetricValue"] { font-size: 1.15rem !important; }
    [data-testid="stMetricLabel"] { font-size: .62rem !important; }
    [data-testid="stMetric"] { padding: 10px 8px !important; }
    .sec-hdr { font-size: .95rem; margin: 1.1rem 0 .6rem; }
    .top-banner { padding: 10px 12px; }
    .top-banner .t { font-size: 1rem; }
    .top-banner .logo { height: 28px; }
    .stTabs [data-baseweb="tab"] { padding: 8px 10px !important; font-size: .78rem !important; }
    .stButton>button { padding: 9px 12px !important; font-size: .88rem !important; }
}
</style>
""", unsafe_allow_html=True)


# ── Top banner & Refresh Button ───────────────────────────────────────────────
# Banner on the left, quick search on the right — the search sits ABOVE the
# tabs so it is reachable from every tab. This row renders on every run, so it
# never shifts the tabs (which would reset the selected tab).
head_l, head_search = st.columns([8, 1], vertical_alignment="center")
with head_l:
    st.markdown(f"""
<div class="top-banner">
  <img class="logo" src="data:image/png;base64,{LOGO_B64}" alt="TLIS" />
  <div>
    <p class="t">Smart Meter Tracker- Vijayawada</p>
  </div>
</div>
""", unsafe_allow_html=True)

# ── Notice area: ONE container, created on every run, above the tabs ─────────
# Streamlit identifies st.tabs by its position on the page. Anything drawn
# above the tabs on only SOME runs (a replayed "✅ saved" message, the map-sync
# warning, the double-count prompt) shifts the tabs down a slot, so Streamlit
# treats them as new tabs and resets to the first one — which is what bounced
# every Excel upload back to the Dashboard. A container that always exists
# occupies exactly one slot whether or not it has content, so everything
# conditional goes INSIDE it and the tabs never move.
_notice_area = st.container()
with _notice_area:
    replay_carried_messages()

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

    sec_hdr("lock", "Supervisor Login")
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
_MISSING = "__worksheet_missing__"


def _is_missing_worksheet(err: Exception) -> bool:
    """A tab that doesn't exist in the Google Sheet. Retrying can never fix
    this, so it must not be retried."""
    text = f"{type(err).__name__} {err}".lower()
    return "worksheetnotfound" in text or "worksheet not found" in text or "unable to parse range" in text


def _is_rate_limited(err: Exception) -> bool:
    text = f"{type(err).__name__} {err}".lower()
    return "429" in text or "quota" in text or "rate_limit" in text or "rate limit" in text


@st.cache_resource
def _sheet_versions() -> dict:
    """Per-worksheet version counters, shared across every user session.

    Bumping ONE sheet's counter makes only that sheet's next read miss the
    cache. The previous approach cleared the entire cache on every write,
    which forced all 9 worksheets to be re-downloaded after saving any one of
    them — ~21 API calls per Analytics upload, so the third section file in a
    minute ran into Google's ~60 reads/min quota. cache_resource (not
    session_state) so a write by one supervisor refreshes it for all of them."""
    return {}


def _sheet_version(worksheet: str) -> int:
    return _sheet_versions().get(worksheet, 0)


def _bump_sheet_version(worksheet: str):
    v = _sheet_versions()
    v[worksheet] = v.get(worksheet, 0) + 1


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def _read_worksheet_cached(worksheet: str, version: int):
    """Cached Sheets read. `version` is bumped by safe_update() so writes
    invalidate the cache immediately.

    NOTE: this parameter must NOT start with an underscore. st.cache_data
    deliberately leaves underscore-prefixed parameters out of the cache key,
    so a `_version` argument is silently ignored — bumping it did nothing and
    every save stayed invisible until the 90s TTL expired, which is why
    uploads and pushes needed repeated clicks to show up.

    A MISSING worksheet is returned as a sentinel rather than raised. That
    matters: st.cache_data never caches exceptions, so a raised "not found"
    was re-requested on every single rerun, five times over with backoff —
    which drained the Sheets read quota (~60/min/user) and then made
    unrelated reads like Locations fail with rate-limit errors. Returning a
    sentinel lets the miss be cached like any other result."""
    try:
        # ttl=0: the connection's internal cache is turned off so this wrapper
        # is the ONLY cache layer. Two layers meant a write could only be made
        # visible by wiping everything; one layer can be invalidated per sheet.
        df = conn.read(worksheet=worksheet, ttl=0)
    except Exception as e:
        if _is_missing_worksheet(e):
            return _MISSING
        raise
    return df.astype(str).fillna("") if not df.empty else pd.DataFrame()


def _rate_limit_cooloff_active() -> bool:
    """True while a rate limit is known to be in force. Without this, EVERY
    sheet in the run retries with 3s + 6s pauses, so one exhausted quota made
    a single page load sleep for over a minute. During the cool-off we fail
    fast instead, and spend no more quota trying."""
    return time.time() < st.session_state.get("_rate_limit_until", 0)


# ── One batched read for every worksheet ────────────────────────────────────
# Google counts a batch request — including all its sub-ranges — as ONE API
# request. Reading the app's worksheets one at a time cost ~2 calls each
# (~22 per refresh); fetching them together costs 1, which is what keeps the
# app clear of the 60-reads-per-minute-per-user quota that produced the
# "limit reached" messages. Falls back to per-sheet reads if anything about
# the batch call fails, so this can never be worse than before.
SHEET_TABS = ("Installations", "Inventory", "Technicians", "Locations", "Supervisors",
              "Settings", "UploadedInstallLog", "AnalyticsRaw", "MapRecords",
              "Expenses", "Vehicles", "Liaisoning")


@st.cache_resource(show_spinner=False)
def _spreadsheet_handle():
    """Opening the spreadsheet is itself an API call, so hold on to it."""
    return conn.client._open_spreadsheet()


def _values_to_df(values) -> pd.DataFrame:
    """Raw cell rows -> DataFrame, first row as the header. Short rows are
    padded: Sheets omits trailing empty cells, so rows arrive ragged."""
    if not values:
        return pd.DataFrame()
    header = [str(h).strip() for h in values[0]]
    width = len(header)
    rows = [(r + [""] * (width - len(r)))[:width] for r in values[1:]]
    return pd.DataFrame(rows, columns=header)


@st.cache_data(ttl=READ_TTL, show_spinner=False)
def _batch_read_sheets(worksheets: tuple, version: int) -> dict:
    """All worksheets in a single API call."""
    sh = _spreadsheet_handle()
    ranges = list(worksheets)
    missing = []
    for _ in range(len(ranges)):
        try:
            resp = sh.values_batch_get([f"'{w}'" for w in ranges])
            break
        except Exception as e:
            # A tab that doesn't exist fails the WHOLE batch ("Unable to parse
            # range: 'Expenses'"), so drop the named one and retry without it.
            m = _re.search(r"[Uu]nable to parse range:\s*'?([^'\"]+?)'?(?:!|\"|$)", str(e))
            name = m.group(1).strip().strip("'") if m else None
            if name and name in ranges:
                ranges.remove(name)
                missing.append(name)
                continue
            raise
    else:
        return {}

    out = {w: _MISSING for w in missing}
    for w, vr in zip(ranges, resp.get("valueRanges", [])):
        df = _values_to_df(vr.get("values", []))
        out[w] = df.astype(str).fillna("") if not df.empty else pd.DataFrame()
    return out


def _batch_version() -> int:
    """Any write to any sheet invalidates the batch, so saves stay instant."""
    return sum(_sheet_versions().values())


def _batched(worksheet: str):
    """The worksheet from the batched read, or None to fall back."""
    if worksheet not in SHEET_TABS or st.session_state.get("_batch_read_off"):
        return None
    try:
        data = _batch_read_sheets(SHEET_TABS, _batch_version())
    except Exception:
        # Don't retry the batch for the rest of this session; per-sheet reads
        # still work, and retrying a broken batch every call would be costly.
        st.session_state["_batch_read_off"] = True
        return None
    return data.get(worksheet)


def get_data(worksheet: str, retries: int = 3) -> pd.DataFrame:
    version = _sheet_version(worksheet)

    batched = _batched(worksheet)
    if batched is not None:
        if isinstance(batched, str) and batched == _MISSING:
            missing = st.session_state.setdefault("_missing_sheets", set())
            if worksheet not in missing:
                missing.add(worksheet)
                st.toast(f"Sheet tab '{worksheet}' not found — create it in Google Sheets.", icon="⚠️")
            return pd.DataFrame()
        return batched.copy()

    if _rate_limit_cooloff_active():
        retries = 1
    for attempt in range(retries):
        try:
            result = _read_worksheet_cached(worksheet, version)
            if isinstance(result, str) and result == _MISSING:
                # Report once per session, not on every rerun.
                missing = st.session_state.setdefault("_missing_sheets", set())
                if worksheet not in missing:
                    missing.add(worksheet)
                    st.toast(f"Sheet tab '{worksheet}' not found — create it in Google Sheets.", icon="⚠️")
                return pd.DataFrame()
            return result.copy()
        except Exception as e:
            if _is_rate_limited(e):
                st.session_state["_rate_limit_until"] = time.time() + 30
            if attempt < retries - 1:
                # Rate limits need a longer pause to let the quota window roll;
                # ordinary blips recover quickly. Capped well under the old
                # 15s so a bad moment doesn't freeze the app.
                time.sleep(3 * (attempt + 1) if _is_rate_limited(e) else 1)
            else:
                reason = "rate limit reached" if _is_rate_limited(e) else "connection drop"
                shown = st.session_state.setdefault("_read_errors", set())
                if worksheet not in shown:
                    shown.add(worksheet)
                    st.toast(f"📡 {reason.capitalize()} loading {worksheet} — tap Refresh in a moment.", icon="⚠️")
                return pd.DataFrame()


def safe_update(worksheet: str, data: pd.DataFrame, retries: int = 3) -> bool:
    """Write to Sheets with retries so a dropped connection doesn't lose the entry.
    On repeated failure, the data the user entered is NOT cleared — they can just retry."""
    for attempt in range(retries):
        try:
            with st.spinner(f"💾 Saving to {worksheet}..."):
                conn.update(worksheet=worksheet, data=data.astype(str))
            # Invalidate ONLY this worksheet. With the connection's own cache
            # disabled (see _read_worksheet_cached) there is a single cache
            # layer, so this is sufficient — and the other 8 sheets stay
            # cached instead of all being re-downloaded after every save.
            _bump_sheet_version(worksheet)
            return True
        except Exception as e:
            if attempt < retries - 1:
                # A rate limit won't clear in a second; hammering it just
                # spends more of the quota that caused it.
                time.sleep(4 * (attempt + 1) if _is_rate_limited(e) else 1)
            else:
                if _is_rate_limited(e):
                    st.error("⚠️ Google Sheets limit reached. Your entries are safe — wait about a minute, then tap Save again.")
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


def clean_id_value(v) -> str:
    """Strip the trailing ".0" Google Sheets adds to numeric cells, so meter and
    consumer numbers read as 643612600001 rather than 643612600001.0. Also
    expands scientific notation, which Sheets uses for long numbers."""
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none"):
        return ""
    if "e" in s.lower():
        try:
            return f"{int(float(s)):d}"
        except Exception:
            return s
    if s.endswith(".0"):
        s = s[:-2]
    return s


# ── Meter type -> phase ──────────────────────────────────────────────────────
# Previously each record was tested with two INDEPENDENT checks — "contains
# 1?" and "contains 3?". MDM meter-type text often carries a current rating
# ("1PH 5-30A", "3PH 10-60A"), which contains both digits, so one install was
# counted as 1PH AND 3PH: the Dashboard (which adds qty_1ph + qty_3ph) came out
# higher than Analytics (which counts rows), and 1PH billing was inflated.
# This reads the PHASE token only and returns exactly one answer per install.
import re as _re
_PH_3 = _re.compile(r"(?<![0-9])3\s*[-_ ]?\s*(?:PH|PHASE|P\b|Ø)|\bTHREE[\s_-]*PHASE\b|\bTHREE\b|\bLTCT\b|\bPOLY[\s_-]*PHASE\b")
_PH_1 = _re.compile(r"(?<![0-9])1\s*[-_ ]?\s*(?:PH|PHASE|P\b|Ø)|\bSINGLE[\s_-]*PHASE\b|\bSINGLE\b")


def classify_meter_type(meter_type) -> str:
    """Return '1PH', '3PH', or '' (unclassified). Never both."""
    s = str(meter_type or "").strip().upper()
    if not s or s in ("NAN", "NONE"):
        return ""
    if s in ("1", "1.0"):
        return "1PH"
    if s in ("3", "3.0"):
        return "3PH"
    has3, has1 = bool(_PH_3.search(s)), bool(_PH_1.search(s))
    if has3 and not has1:
        return "3PH"
    if has1 and not has3:
        return "1PH"
    if has3 and has1:
        # Both phase words present — take whichever phase token comes first.
        return "3PH" if _PH_3.search(s).start() < _PH_1.search(s).start() else "1PH"
    return ""


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


def build_weekly_report_pdf(date_start, date_end, section_filter=None, meter_type_filter: str = "All",
                            location_filter=None):
    """Builds a single-page PDF for sharing with the customer: install
    quantities by date and section code, plus a small real-basemap snippet
    per section code showing where those installs are.

    Two levels of "section" exist and they are not the same thing:
      * Section (Location) — the named area on the record, e.g. CHITTINAGAR
      * Section code       — the 2-digit code parsed from the Consumer No/SNO,
                             several of which sit under one Location
    location_filter narrows by the former, section_filter by the latter.

    Pulls only from UploadedInstallLog — the same ledger the Dashboard/
    Installations totals are built from — so the numbers here always match
    the official install counts, never Map-only legacy data. Returns
    (pdf_bytes, error_message); pdf_bytes is None if error_message is set."""
    df = get_data("UploadedInstallLog")
    if df.empty or not has_col(df, "date", "sno", "meter_type"):
        return None, "No install data available yet."

    df = df.copy()
    df["_date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df[(df["_date"] >= date_start) & (df["_date"] <= date_end)]
    if meter_type_filter != "All":
        # Classify rather than exact-match: real values carry ratings
        # ("1PH 5-30A") and would never equal the plain "1 PH" label.
        want = "1PH" if "1" in meter_type_filter else "3PH"
        df = df[df["meter_type"].apply(classify_meter_type) == want]
    if location_filter and "location" in df.columns:
        df = df[df["location"].astype(str).str.strip().isin(location_filter)]
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
                # Frame each snippet on its group of installs; a stray pin
                # would otherwise shrink the whole section into one corner.
                _la, _lo = sub["_lat"].tolist(), sub["_long"].tolist()
                _stray = split_stray_pins(_la, _lo)
                _la = [v for v, s in zip(_la, _stray) if not s] or _la
                _lo = [v for v, s in zip(_lo, _stray) if not s] or _lo
                png = build_basemap_snapshot_png(_la, _lo, title=f"{sec} - {loc_name}" if loc_name else f"Section {sec}")
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

    # Letterhead: logo left, title + meta to its right.
    header_top = pdf.get_y()
    text_x = pdf.l_margin
    try:
        logo_h = 13.0
        logo_img = Image.open(io.BytesIO(base64.b64decode(LOGO_PRINT_B64)))
        logo_w = logo_h * (logo_img.width / logo_img.height)
        pdf.image(io.BytesIO(base64.b64decode(LOGO_PRINT_B64)), x=pdf.l_margin, y=header_top, h=logo_h)
        text_x = pdf.l_margin + logo_w + 5
    except Exception:
        pass  # logo is decoration — never block the report over it

    pdf.set_xy(text_x, header_top)
    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(16, 21, 31)
    pdf.cell(0, 8, "Installation Report", ln=1)

    pdf.set_x(text_x)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(0, 138, 150)
    pdf.cell(0, 5, COMPANY_NAME, ln=1)

    pdf.set_y(max(pdf.get_y(), header_top + 14) + 1)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 105, 115)
    loc_desc = "All Sections" if not location_filter else ", ".join(location_filter)
    code_desc = "All Codes" if not section_filter else ", ".join(section_filter)
    pdf.cell(0, 6, f"Period: {date_start.isoformat()} to {date_end.isoformat()}   |   Meter Type: {meter_type_filter}", ln=1)
    pdf.cell(0, 5, f"Section: {loc_desc}   |   Section Codes: {code_desc}", ln=1)
    pdf.cell(0, 5, f"Generated: {today_ist().isoformat()}", ln=1)
    pdf.ln(2)
    # Brand rule under the letterhead.
    pdf.set_draw_color(0, 180, 192)
    pdf.set_line_width(0.6)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.set_line_width(0.2)
    pdf.set_draw_color(0, 0, 0)
    pdf.ln(3)

    # -- Quantity table --
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(16, 21, 31)
    pdf.cell(0, 6, "Installation Quantities By Date & Section Code", ln=1)
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
            pdf.multi_cell(avail_w, 4, f"Section codes:  {legend}")
            pdf.ln(1)

    # -- Map snippets grid (fits remaining space on this one page) --
    if shown_snippets:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "Install Locations By Section Code", ln=1)

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

    def _draw_footer():
        """Footer rule + company line, pinned to the bottom of the current page."""
        y = pdf.h - pdf.b_margin - 6
        pdf.set_draw_color(220, 224, 230)
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.set_xy(pdf.l_margin, y + 1)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(140, 145, 155)
        pdf.cell(0, 4, f"{COMPANY_NAME}  |  Generated by Meter Tracker", align="C")

    # ── Installed consumer service numbers ────────────────────────────────
    # Laid out in side-by-side column blocks so a long list stays compact:
    # three blocks per page fits roughly 3x the rows of a single full-width
    # table, which matters when a week can run to hundreds of installs.
    listing = df.sort_values(["_date", "time"]) if "time" in df.columns else df.sort_values("_date")
    records = [
        (clean_id_value(r.get("sno", "")), str(r.get("installer_id", "")).strip())
        for _, r in listing.iterrows()
    ]
    records = [(s, i) for s, i in records if s]

    if records:
        N_BLOCKS = 3
        blk_gap = 4.0
        blk_w = (avail_w - blk_gap * (N_BLOCKS - 1)) / N_BLOCKS
        w_sl, w_sno = blk_w * 0.16, blk_w * 0.47
        w_inst = blk_w - w_sl - w_sno
        lh = 4.2          # line height
        font_sz = 6.5

        def _list_header(x, y):
            pdf.set_xy(x, y)
            pdf.set_font("Helvetica", "B", font_sz)
            pdf.set_fill_color(16, 21, 31)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(w_sl, lh, "#", border=1, align="C", fill=True)
            pdf.cell(w_sno, lh, "Consumer No", border=1, align="C", fill=True)
            pdf.cell(w_inst, lh, "Installer", border=1, align="C", fill=True)

        def _start_list_page(first=False):
            if not first:
                _draw_footer()
                pdf.add_page()
            pdf.set_xy(pdf.l_margin, pdf.get_y())
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(16, 21, 31)
            pdf.cell(0, 6, "Installed Consumer Service Numbers", ln=1)
            return pdf.get_y()

        # Continue on the current page if there's meaningful room, else start fresh.
        room = pdf.h - pdf.b_margin - 10 - pdf.get_y()
        if room < 40:
            top_y = _start_list_page(first=False)
        else:
            pdf.ln(2)
            top_y = _start_list_page(first=True)

        def _rows_that_fit(y):
            """Recomputed per page: page 1 shares space with the table and maps,
            later pages have the full height, so a fixed count would waste most
            of every continuation page."""
            return max(1, int((pdf.h - pdf.b_margin - 10 - y - lh) // lh))

        rows_per_block = _rows_that_fit(top_y)
        per_page = rows_per_block * N_BLOCKS

        idx = 0
        while idx < len(records):
            page_slice = records[idx:idx + per_page]
            for b in range(N_BLOCKS):
                chunk = page_slice[b * rows_per_block:(b + 1) * rows_per_block]
                if not chunk:
                    break
                x = pdf.l_margin + b * (blk_w + blk_gap)
                _list_header(x, top_y)
                y = top_y + lh
                for j, (sno, inst) in enumerate(chunk):
                    serial = idx + b * rows_per_block + j + 1
                    pdf.set_xy(x, y)
                    pdf.set_font("Helvetica", "", font_sz)
                    pdf.set_fill_color(255, 255, 255) if j % 2 == 0 else pdf.set_fill_color(246, 247, 249)
                    pdf.set_text_color(16, 21, 31)
                    pdf.cell(w_sl, lh, str(serial), border=1, align="C", fill=True)
                    pdf.cell(w_sno, lh, sno, border=1, align="C", fill=True)
                    pdf.cell(w_inst, lh, inst, border=1, align="C", fill=True)
                    y += lh
            idx += per_page
            if idx < len(records):
                top_y = _start_list_page(first=False)
                rows_per_block = _rows_that_fit(top_y)
                per_page = rows_per_block * N_BLOCKS

        pdf.set_y(pdf.h - pdf.b_margin - 12)
        pdf.set_font("Helvetica", "I", 7.5)
        pdf.set_text_color(120, 125, 135)
        pdf.cell(0, 4, f"Total: {len(records)} consumer service number(s) for the selected period and filters.", ln=1)

    _draw_footer()
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


class _Cell:
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class _SheetGrid:
    """In-memory stand-in for an openpyxl worksheet exposing just the
    .cell(row=, column=).value and .max_row / .max_column the parsers use.

    openpyxl's read-only mode loads far faster, but random cell access in that
    mode rescans the file on every call — worse than a normal load. Streaming
    the rows once into memory gets the fast load AND fast random access, with
    no change needed at any of the call sites."""

    def __init__(self, rows):
        self._rows = rows
        self.max_row = len(rows)
        self.max_column = max((len(r) for r in rows), default=0)

    def cell(self, row: int, column: int):
        try:
            return _Cell(self._rows[row - 1][column - 1])
        except IndexError:
            return _Cell(None)


def load_first_data_sheet(uploaded_file):
    """Return the primary data worksheet from an uploaded workbook, skipping
    any pre-computed pivot/summary sheets (e.g. 'LoginID_Summary')."""
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    wb = openpyxl.load_workbook(uploaded_file, data_only=True, read_only=True)
    try:
        name = next((n for n in wb.sheetnames if "summary" not in n.strip().lower()), wb.sheetnames[0])
        return _SheetGrid([tuple(r) for r in wb[name].iter_rows(values_only=True)])
    finally:
        wb.close()  # read-only workbooks hold the file open until closed


def time_to_minutes(hhmmss: str) -> float:
    h, m, s = hhmmss.split(":")
    return int(h) * 60 + int(m) + int(s) / 60.0


def compute_active_pace(sorted_times, break_threshold: float = BREAK_GAP_THRESHOLD_MIN):
    """Hands-on pace: the mean gap between consecutive installs, EXCLUDING any
    gap longer than break_threshold (lunch, travel between sections, waiting
    for consumer access). Answers "how fast is this installer actually
    working?" — so one long break can't make a fast installer look slow.

    Note this is deliberately NOT what the forecast uses: a forecast projects
    over future wall-clock time that will itself contain breaks, so it needs
    the break-inclusive throughput rate instead (see forecast_total_installs).

    Returns (active_pace_min, break_minutes, working_gap_count); active_pace
    is None when there aren't at least two installs, or when every gap was a
    break — in both cases there's no observed working rhythm to report."""
    mins = [time_to_minutes(t) for t in sorted_times]
    if len(mins) < 2:
        return None, 0.0, 0
    gaps = [mins[i] - mins[i - 1] for i in range(1, len(mins))]
    working = [g for g in gaps if g <= break_threshold]
    break_minutes = sum(g for g in gaps if g > break_threshold)
    if not working:
        return None, break_minutes, 0
    return sum(working) / len(working), break_minutes, len(working)



FORECAST_MIN_ELAPSED_HOURS = 1.0  # floor on measured elapsed time (see below)


def forecast_total_installs(day_df: pd.DataFrame, installers: list, day_end_str: str = FORECAST_DAY_END):
    """Projects the team's likely total installs by day-end from the team-wide
    hourly rate:

        elapsed   = last install time - first install time  (pro-rated, so a
                    part-finished hour is counted as the minutes actually
                    worked, not as a whole hour)
        rate      = installs so far / elapsed hours
        forecast  = installs so far + rate x hours remaining to day end

    Why team-hourly rather than per-installer pace: the hourly rate absorbs
    everything that actually happens on site — breaks (taken at random times
    here, not a fixed lunch), travel between consumers, an afternoon
    slowdown, people finishing early. A slow spell pulls the rate down and a
    strong one pulls it back up, so the forecast self-corrects without a
    separate trend adjustment.

    Pro-rating matters when data is uploaded mid-hour: 60 installs from 09:00
    to 11:30 is 2.5 hours of work at 24/hour, but counting three whole clock
    hours (9, 10, 11) would report 20/hour and under-forecast by ~26 installs.

    FORECAST_MIN_ELAPSED_HOURS floors the elapsed figure because pro-rating
    divides by it: two installs three minutes apart would otherwise imply
    40 installs/hour and forecast 360 for the day. The floor costs nothing in
    accuracy (measured identical at 0.5h, 1.0h and 1.5h) and removes that
    failure mode.

    Benchmarked over 80 simulated days x 24 check times spread across the hour:
    mean error 4.6%, median 3.5%.

    Returns (rounded_total, rate_per_hour, effective_day_end), or
    (None, 0.0, day_end_str) when there isn't enough data yet to project."""
    if not installers or day_df.empty:
        return None, 0.0, day_end_str

    valid = day_df.dropna(subset=["hour_int"]) if "hour_int" in day_df.columns else day_df
    if valid.empty or len(valid) < 2:
        return None, 0.0, day_end_str

    total_so_far = len(valid)
    mins = [time_to_minutes(t) for t in valid["time"]]
    first_min, last_min = min(mins), max(mins)

    elapsed_hours = max((last_min - first_min) / 60.0, FORECAST_MIN_ELAPSED_HOURS)
    rate_per_hour = total_so_far / elapsed_hours

    # Project from the last recorded install, not wall-clock "now": Analytics
    # only advances when a file is uploaded, so the clock can be well ahead of
    # the data and would invent hours of progress that were never measured.
    day_end_min = time_to_minutes(day_end_str)

    # If the team is still installing past the assumed finish time, the day
    # plainly hasn't ended. Without this the forecast silently collapses to
    # "whatever has been done so far" and stops predicting anything — at 19:00
    # on a 18:00 day-end it would report the current count as the final total.
    # Roll the horizon forward to the next whole hour after the last install
    # so it keeps projecting while work is evidently ongoing.
    if last_min >= day_end_min:
        day_end_min = (math.floor(last_min / 60) + 1) * 60

    hours_remaining = max(0.0, (day_end_min - last_min) / 60.0)
    effective_end = f"{int(day_end_min // 60):02d}:{int(day_end_min % 60):02d}"

    return round(total_so_far + rate_per_hour * hours_remaining), rate_per_hour, effective_end


# ── Shared data fetched once per run (avoids repeat reads across tabs) ──────
df_installations_master = get_data("Installations")
df_inventory_master = get_data("Inventory")
df_technicians_master = get_data("Technicians")
df_locations_master = get_data("Locations")
df_supervisors_master = get_data("Supervisors")
df_settings_master = get_data("Settings")


def get_setting(key: str, default):
    """App settings live in a simple key/value sheet so they can be changed in
    Admin without a redeploy.  Settings sheet: key, value"""
    if df_settings_master.empty or not has_col(df_settings_master, "key", "value"):
        return default
    row = df_settings_master[df_settings_master["key"].astype(str).str.strip() == key]
    if row.empty:
        return default
    raw = str(row.iloc[0]["value"]).strip()
    if raw == "":
        return default
    try:
        return type(default)(float(raw)) if isinstance(default, (int, float)) else raw
    except Exception:
        return default


def save_setting(key: str, value) -> bool:
    df = df_settings_master.copy()
    if df.empty or not has_col(df, "key", "value"):
        df = pd.DataFrame(columns=["key", "value"])
    mask = df["key"].astype(str).str.strip() == key if not df.empty else pd.Series([], dtype=bool)
    if not df.empty and mask.any():
        df.loc[mask, "value"] = str(value)
    else:
        df = pd.concat([df, pd.DataFrame([{"key": key, "value": str(value)}])], ignore_index=True)
    return safe_update("Settings", df)


MONTHLY_TARGET = int(get_setting("monthly_install_target", DEFAULT_MONTHLY_TARGET))


# ── Expenses: cost per install ─────────────────────────────────────────────
# Every figure is computed live from the Expenses and Vehicles sheets, so any
# change to a cost shows up in the per-install numbers straight away.
#   Fixed    — amounts for the calendar month (rent, salaries, vehicles...).
#   Variable — RATES per install, multiplied by that month's installs.
#              1PH and 3PH have separate rates, since 3PH work is often paid
#              differently; leave the 3PH rate at 0 if it isn't.
EXPENSE_COLS = ["expense_id", "month", "cost_type", "category", "item", "vehicle_reg",
                "amount", "rate_1ph", "rate_3ph", "recurring"]
VEHICLE_COLS = ["reg_no", "description", "is_active"]

# ── Daily install calendar ─────────────────────────────────────────────────
# Reads the install log, not AnalyticsRaw: a month-long view needs full
# history, and AnalyticsRaw only holds recent uploads and is cleared by the
# end-of-day reset.
# Daily-volume bands for the calendar: under 100 red, 100-199 orange,
# 200-299 yellow, 300+ green. Uses the app's conditional-formatting pairs so
# the colours match the rest of the app and stay readable.
DAY_VOLUME_BANDS = (100, 200, 300)


def day_volume_colors(n: int):
    if n < DAY_VOLUME_BANDS[0]:
        return CF_RED_BG, CF_RED_FONT
    if n < DAY_VOLUME_BANDS[1]:
        return CF_ORANGE_BG, CF_ORANGE_FONT
    if n < DAY_VOLUME_BANDS[2]:
        return CF_YELLOW_BG, CF_YELLOW_FONT
    return CF_GREEN_BG, CF_GREEN_FONT


def month_daily_counts(mkey: str) -> dict:
    """{date -> installs} for a calendar month."""
    df = get_data("UploadedInstallLog")
    if df.empty or "date" not in df.columns:
        return {}
    d = pd.to_datetime(df["date"], errors="coerce")
    sub = df[d.dt.strftime("%Y-%m") == mkey]
    if sub.empty:
        return {}
    return sub.groupby("date").size().to_dict()


def day_section_breakup(day: str) -> pd.DataFrame:
    """Section-wise installs for one date, with the 1PH/3PH split."""
    df = get_data("UploadedInstallLog")
    if df.empty or "date" not in df.columns:
        return pd.DataFrame()
    sub = df[df["date"].astype(str) == str(day)].copy()
    if sub.empty:
        return pd.DataFrame()
    sub["location"] = (sub["location"].astype(str).str.strip().replace("", "Unspecified")
                       if "location" in sub.columns else "Unspecified")
    phase = sub["meter_type"].apply(classify_meter_type) if "meter_type" in sub.columns else ""
    sub["_1"] = (phase == "1PH").astype(int)
    sub["_3"] = (phase == "3PH").astype(int)
    out = sub.groupby("location").agg(Installs=("date", "size"), **{"1PH": ("_1", "sum"), "3PH": ("_3", "sum")}).reset_index()
    out = out.rename(columns={"location": "Section"}).sort_values("Installs", ascending=False)
    total = {"Section": "TOTAL", "Installs": int(out["Installs"].sum()),
             "1PH": int(out["1PH"].sum()), "3PH": int(out["3PH"].sum())}
    return pd.concat([out, pd.DataFrame([total])], ignore_index=True)


@st.fragment
def render_daily_calendar(mkey: str):
    """Month calendar of daily totals, a chart of the same, and the section
    breakup for whichever day is tapped.

    A fragment: tapping a day reruns only this block, not all eight tabs."""
    import calendar as _cal
    counts = month_daily_counts(mkey)
    if not counts:
        st.info(f"No installs recorded in {month_label(mkey)}.")
        return

    y, m = int(mkey[:4]), int(mkey[5:])
    picked = st.session_state.get("cal_picked_day")
    if picked not in counts:
        picked = max(counts)          # default: the latest day with installs

    # Each day is a real button, so it is coloured through Streamlit's
    # per-widget class (st-key-<key>) rather than inline styles. The
    # background/text pairs are the app's conditional-formatting colours,
    # which clear the contrast bar.
    rules = []
    for dstr, n in counts.items():
        bg, fg = day_volume_colors(int(n))
        sel = ("border:2px solid var(--ink-900) !important;"
               if dstr == picked else "border:1px solid var(--hairline) !important;")
        # The day number is added ABOVE the count with ::before, because a
        # button's own label renders on a single line — date and count were
        # ending up side by side. flex-direction:column stacks them.
        rules.append(
            f'.st-key-cal_{dstr} button {{background:{bg} !important;color:{fg} !important;'
            f'{sel}display:flex !important;flex-direction:column !important;gap:1px !important;'
            f'line-height:1.15 !important;padding:7px 2px !important;min-height:0 !important;}}'
            f'.st-key-cal_{dstr} button::before {{content:"{int(dstr[-2:])}";display:block;'
            f'font-size:10.5px;font-weight:700;opacity:.75;}}'
            f'.st-key-cal_{dstr} button p {{font-size:15px !important;font-weight:800 !important;'
            f'margin:0 !important;}}')
    # On a narrow screen Streamlit stacks a row of columns vertically, which
    # turned each week into 7 full-width bars. Keep the calendar's rows
    # side-by-side and size the cells down instead.
    rules.append(
        '[class*="st-key-calweek_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap !important;gap:3px !important;}'
        '[class*="st-key-calweek_"] [data-testid="stColumn"]{flex:1 1 0 !important;min-width:0 !important;width:auto !important;}'
        '@media (max-width:640px){'
        '[class*="st-key-calweek_"] button{padding:5px 0 !important;}'
        '[class*="st-key-calweek_"] button p{font-size:12.5px !important;}'
        '[class*="st-key-calweek_"] button::before{font-size:9px !important;}'
        '.cal-empty{padding:5px 0 !important;}'
        '.cal-empty div:first-child{font-size:9px !important;}'
        '.cal-empty div:last-child{font-size:12.5px !important;}'
        '}')
    st.markdown("<style>" + "".join(rules) + "</style>", unsafe_allow_html=True)

    st.markdown(
        '<div style="display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:var(--space-2);'
        'margin-bottom:var(--space-2);">'
        + "".join(f'<div style="text-align:center;font-size:11px;font-weight:700;color:var(--ink-600);">{d}</div>'
                  for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))
        + "</div>", unsafe_allow_html=True)

    # CSS below keys off this container, so only the calendar's rows are
    # forced to stay 7-across — every other st.columns in the app keeps
    # Streamlit's normal stacking on a phone.
    for wk, week in enumerate(_cal.Calendar(firstweekday=0).monthdayscalendar(y, m)):
      with st.container(key=f"calweek_{mkey}_{wk}"):
        cols = st.columns(7, gap="small")
        for col, dayno in zip(cols, week):
            with col:
                if dayno == 0:
                    st.markdown("<div style='height:1px;'></div>", unsafe_allow_html=True)
                    continue
                dstr = f"{y:04d}-{m:02d}-{dayno:02d}"
                n = int(counts.get(dstr, 0))
                # A day with no installs isn't clickable — there is nothing to
                # break up, and a dead button invites a pointless rerun.
                if n == 0:
                    # Styled like a day cell but not a button: there is no
                    # breakup to show for a day with nothing on it. A day still
                    # in the future isn't a shortfall, so it stays neutral —
                    # only days up to today count as a red zero.
                    future = date(y, m, dayno) > today_ist()
                    bg = "var(--surface-000)" if future else CF_RED_BG
                    fg = "var(--ink-600)" if future else CF_RED_FONT
                    st.markdown(
                        f'<div class="cal-empty" style="text-align:center;border-radius:var(--radius-sm);'
                        f'border:1px solid var(--hairline);background:{bg};color:{fg};'
                        f'padding:7px 2px;line-height:1.15;">'
                        f'<div style="font-size:10.5px;font-weight:700;opacity:.75;">{dayno}</div>'
                        f'<div style="font-size:15px;font-weight:800;'
                        + ('opacity:.45;' if future else '') +
                        f'">-</div></div>',
                        unsafe_allow_html=True)
                    continue
                # Label is the count only; the day number comes from the CSS
                # above it (see the ::before rule).
                if st.button(f"{n}", key=f"cal_{dstr}", use_container_width=True,
                             type=("primary" if dstr == picked else "secondary"),
                             help=f"{n} install(s) on {dstr}"):
                    # No explicit rerun: a button inside a fragment already
                    # reruns the fragment, and st.rerun(scope="fragment") is
                    # invalid on a full-script run, which is when the first
                    # click happens.
                    st.session_state["cal_picked_day"] = dstr
                    picked = dstr

    # Min ignores zero days: a day nobody worked says nothing about the worst
    # day's output, and would always read 0 once the month has a gap in it.
    # Holidays are counted only up to today — a day still to come isn't a day
    # off, which is the same rule the calendar's colouring follows.
    worked = {d: int(n) for d, n in counts.items() if int(n) > 0}
    if worked:
        hi_day = max(worked, key=worked.get)
        lo_day = min(worked, key=worked.get)
        last_day_n = _cal.monthrange(y, m)[1]
        holidays = [d for d in range(1, last_day_n + 1)
                    if date(y, m, d) <= today_ist()
                    and int(counts.get(f"{y:04d}-{m:02d}-{d:02d}", 0)) == 0]
        fmt_day = lambda ds: datetime.strptime(ds, "%Y-%m-%d").strftime("%d %b")
        render_stat_tiles([
            ("chart", f"{worked[hi_day]:,}", "Max", fmt_day(hi_day), "normal"),
            ("gauge", f"{worked[lo_day]:,}", "Min", fmt_day(lo_day), "normal"),
            ("calendar", f"{len(holidays)}", "Holidays", "no installs",
             "danger" if holidays else "normal"),
        ])

    sub_hdr("pin", f"Section-Wise On {picked}")
    breakup = day_section_breakup(picked)
    if breakup.empty:
        st.info("No records for that date.")
    else:
        st.dataframe(breakup, use_container_width=True, hide_index=True,
                     height=dataframe_height(len(breakup)))
        download_image_button(breakup, f"Sections_{picked}.png", key="dl_img_cal_day",
                              title=f"Section-Wise Installs — {picked}")

    # Chart of the same daily totals, across the whole month.
    last_day = _cal.monthrange(y, m)[1]
    series = pd.DataFrame(
        {"Installs": [int(counts.get(f"{y:04d}-{m:02d}-{d:02d}", 0)) for d in range(1, last_day + 1)]},
        index=pd.Index(range(1, last_day + 1), name=f"Day of {month_label(mkey)}"))
    st.bar_chart(series, height=240)



# ── 1PH Incentive & Profit Sharing workbook ────────────────────────────────
# The approved calculator, kept as a live Excel file: the app fills in the
# inputs (installs from the install log, expense per install from the Expenses
# tab) and leaves every formula in place, so it still recalculates when you
# edit it in Excel.
INCENTIVE_OLD_UNIT_RATE_1PH = 150.0   # pre-hike rate, for the profit split
RETENTION_PCT = 0.15                  # held 90 days on the old base amount
GST_PCT = 0.09
PRIMARY_SPLIT = 0.50                  # Sandeep's share of the Sandeep+Raghu pool
PARTNERS = ("Sandeep", "Raghu", "Kiran", "Manju")   # first two are primary
INCENTIVE_TEMPLATE_B64 = "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"


def month_installs_1ph(mkey: str) -> int:
    """1PH installs for a calendar month, counted from the install log — the
    same ledger the Dashboard and the Customer Report use."""
    df = get_data("UploadedInstallLog")
    if df.empty or not has_col(df, "date", "meter_type"):
        return 0
    d = df[pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m") == mkey]
    if d.empty:
        return 0
    return int((d["meter_type"].apply(classify_meter_type) == "1PH").sum())


def profit_sharing_summary(installs: int, cost_per_install: float, old_rate: float,
                           new_rate: float, survey: float, retention_pct: float,
                           gst_pct: float, split: float) -> dict:
    """The Profit Sharing sheet's arithmetic, in Python, so the app can show
    the same figures the downloaded workbook will compute."""
    old_base_revenue = (old_rate + survey) * installs
    expense_total = cost_per_install * installs
    base_profit = old_base_revenue - expense_total
    retention = retention_pct * old_base_revenue
    gst_old = gst_pct * old_base_revenue
    price_hike = (new_rate - old_rate) * installs
    tier_incentive = calculate_1ph_incentive_billing(installs)["tier_incentive"]
    additional = price_hike + tier_incentive
    gst_additional = gst_pct * additional

    quarter = lambda x: x / 4.0
    rows = []
    for i, name in enumerate(PARTNERS):
        primary = i < 2
        share_add = (split if i == 0 else (1 - split)) if primary else 0.0
        base_s, ret_s, gst_s = quarter(base_profit), quarter(retention), quarter(gst_old)
        add_s, gadd_s = additional * share_add, gst_additional * share_add
        rows.append({
            "Partner": name,
            "Base Profit Share": base_s,
            "GST On Old Base": gst_s,
            "Additional (New Pricing)": add_s,
            "GST On Additional": gadd_s,
            "Payable Now": base_s + gst_s + add_s + gadd_s,
            "Retention (after 90 days)": ret_s,
            "Grand Total": base_s + gst_s + add_s + gadd_s + ret_s,
        })
    return {
        "installs": installs, "cost_per_install": cost_per_install,
        "old_base_revenue": old_base_revenue, "expense_total": expense_total,
        "base_profit": base_profit, "retention": retention, "gst_old": gst_old,
        "price_hike": price_hike, "tier_incentive": tier_incentive,
        "additional": additional, "gst_additional": gst_additional,
        "partners": pd.DataFrame(rows),
    }


def build_incentive_workbook(mkey: str, installs: int, cost_per_install: float,
                             old_rate: float, retention_pct: float, gst_pct: float,
                             split: float) -> bytes:
    """Fill the approved template's INPUT cells and hand back the workbook.
    Formulas are untouched, so Excel recalculates everything on open."""
    wb = openpyxl.load_workbook(io.BytesIO(base64.b64decode(INCENTIVE_TEMPLATE_B64)))
    calc = wb["1Ph Incentive Calc"]
    calc["B5"] = INCENTIVE_UNIT_RATE_1PH          # new unit rate
    calc["B6"] = INCENTIVE_FLAT_ADDON_1PH         # survey add-on
    calc["B7"] = installs                         # <- from the install log
    calc["E5"] = old_rate
    calc["E6"] = INCENTIVE_FLAT_ADDON_1PH
    calc["E7"] = installs
    calc["A3"] = f"Month: {month_label(mkey)}  |  1PH installs from the install log: {installs:,}"

    ps = wb["Profit Sharing"]
    ps["B10"] = round(float(cost_per_install), 2)  # <- from the Expenses tab
    ps["C10"] = f"From the Expenses tab — {month_label(mkey)} total cost / install"
    ps["B11"] = retention_pct
    ps["B12"] = gst_pct
    ps["B13"] = split

    # Retention calendar starts at the selected month, invoiced on the 1st of
    # the next month (the sheet's own rule).
    y, m = int(mkey[:4]), int(mkey[5:])
    ps["A42"] = month_label(mkey)
    ps["B42"] = datetime(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    for i in range(1, 12):
        mm, yy = (m + i - 1) % 12 + 1, y + (m + i - 1) // 12
        ps.cell(row=42 + i, column=1).value = datetime(yy, mm, 1).strftime("%b %Y")
    ps["A55"] = (f"Installs, and the expense per install, are taken from the app for "
                 f"{month_label(mkey)}. Later months in this calendar reuse the same "
                 f"figures until their actual quantities are known.")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Liaisoning: section codes -> lineman -> payable ────────────────────────
# Section code = the 6th and 7th digits of the Consumer No / SNO
# (6436407109849 -> "07"), the same rule the Customer Report uses. Each
# lineman covers several section codes within a section (location), and is
# paid per install in those codes.
#   Liaisoning sheet: location, section_code, lineman, rate
# One row per (location, section code): that pair is what a lineman is paid
# for, and the same code can exist under two locations.
LIAISONING_COLS = ["location", "section_code", "lineman", "rate"]


def section_key(name) -> str:
    """Match key for a section name. Install data comes from the MDM export
    ("CHITTINAGAR") while mappings are typed or picked ("Chittinagar"), and an
    exact string match silently drops the mapping — so compare on this."""
    return " ".join(str(name).strip().upper().split())


def normalize_section_code(v) -> str:
    """Section codes are always two digits. Google Sheets stores "07" as the
    NUMBER 7, so it comes back as "7" (or "7.0") and would never match the
    "07" read off a Consumer No — the mapping then looked unmapped. Normalise
    on the way in, which also repairs codes already saved that way."""
    t = str(v).strip()
    if t.endswith(".0"):
        t = t[:-2]
    return f"{int(t):02d}" if t.isdigit() and len(t) <= 2 else t


def parse_section_codes(text: str):
    """'07, 12 26' or a range '07-12' -> ['07','12',...]. Codes are the 6th and
    7th digits of a Consumer No, so they are always two digits: 7 becomes 07."""
    out, seen = [], set()
    # Close up spaces around a dash first, so "07 - 09" is one range and not
    # two separate codes with the range silently lost.
    text = _re.sub(r"\s*[-–]\s*", "-", str(text or "").strip())
    for chunk in _re.split(r"[,\s]+", text):
        if not chunk:
            continue
        rng = _re.fullmatch(r"(\d{1,2})\s*[-–]\s*(\d{1,2})", chunk)
        vals = (range(int(rng.group(1)), int(rng.group(2)) + 1) if rng
                else ([int(chunk)] if chunk.isdigit() and len(chunk) <= 2 else []))
        for v in vals:
            code = f"{v:02d}"
            if code not in seen:
                seen.add(code)
                out.append(code)
    return out


def load_liaisoning() -> pd.DataFrame:
    df = get_data("Liaisoning")
    if df.empty:
        df = pd.DataFrame(columns=LIAISONING_COLS)
    df = df.copy()
    for c in LIAISONING_COLS:
        if c not in df.columns:
            df[c] = ""
    df["rate"] = pd.to_numeric(df["rate"], errors="coerce").fillna(0.0)
    for c in ("location", "section_code", "lineman"):
        df[c] = df[c].astype(str).str.strip()
    df["section_code"] = df["section_code"].apply(normalize_section_code)
    return df


def month_section_counts(mkey: str) -> pd.DataFrame:
    """Installs per (location, section code) for a calendar month, from the
    install log — the same ledger the Dashboard totals come from."""
    df = get_data("UploadedInstallLog")
    if df.empty or not has_col(df, "date", "sno"):
        return pd.DataFrame(columns=["location", "section_code", "installs"])
    df = df.copy()
    df = df[pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m") == mkey]
    if df.empty:
        return pd.DataFrame(columns=["location", "section_code", "installs"])
    df["section_code"] = df["sno"].apply(extract_section_code)
    df["location"] = (df["location"].astype(str).str.strip().replace("", "Unspecified")
                      if "location" in df.columns else "Unspecified")
    out = df.groupby(["location", "section_code"]).size().reset_index(name="installs")
    return out.sort_values(["location", "section_code"]).reset_index(drop=True)


def liaisoning_table(mkey: str) -> pd.DataFrame:
    """Every section code worked in the month, with its lineman, rate and
    payable. Codes with no mapping yet are kept, with a blank lineman, so
    they are visible rather than silently unpaid."""
    counts = month_section_counts(mkey)
    mapping = load_liaisoning()
    if counts.empty and mapping.empty:
        return pd.DataFrame(columns=["location", "section_code", "installs", "lineman", "rate", "payable"])
    if counts.empty:
        counts = pd.DataFrame(columns=["location", "section_code", "installs"])
    # Matched on a normalised section name, so capitalisation or spacing
    # differences between the install data and the mapping can't drop a lineman.
    counts = counts.assign(_key=counts["location"].apply(section_key))
    mapping = mapping.assign(_key=mapping["location"].apply(section_key))
    # OUTER join: every MAPPED code appears even with no installs this month
    # (so the lineman list is complete), and any code with installs but no
    # mapping still shows up to be flagged.
    merged = counts.merge(mapping, on=["_key", "section_code"], how="outer", suffixes=("", "_map"))
    # Show the name as it appears in the install data, falling back to the
    # mapping's spelling for codes with no installs yet.
    merged["location"] = merged["location"].fillna(merged.get("location_map"))
    merged["installs"] = pd.to_numeric(merged["installs"], errors="coerce").fillna(0).astype(int)
    merged["lineman"] = merged["lineman"].fillna("").astype(str)
    merged["rate"] = pd.to_numeric(merged["rate"], errors="coerce").fillna(0.0)
    merged["payable"] = merged["installs"] * merged["rate"]
    cols = ["location", "section_code", "installs", "lineman", "rate", "payable"]
    return merged[cols].sort_values(["location", "section_code"]).reset_index(drop=True)


# Upper end of the "Cost At Any Install Count" slider.
EXPENSE_SLIDER_MAX = 14000

EXPENSE_FIXED_CATEGORIES = [
    "Accommodation (Rent)", "Salaries", "Vehicle EMI", "Vehicle Maintenance",
    "Vehicle Permits", "Diesel", "Travel", "Misc",
]
EXPENSE_VARIABLE_CATEGORIES = ["Installer Payment", "Liaisoning"]
# Costs that belong to a particular vehicle (chosen from the Vehicles list).
EXPENSE_VEHICLE_CATEGORIES = {"Vehicle EMI", "Vehicle Maintenance", "Vehicle Permits", "Diesel"}
# Costs that are usually the same every month — pre-ticked as "repeats monthly"
# so "Copy repeating costs from last month" can carry them forward.
EXPENSE_RECURRING_DEFAULT = {"Accommodation (Rent)", "Salaries", "Vehicle EMI"}
EXPENSE_ITEM_HINT = {
    "Accommodation (Rent)": "e.g. Team room, Benz Circle",
    "Salaries": "e.g. Supervisor – Surendra",
    "Vehicle EMI": "e.g. Bolero loan EMI",
    "Vehicle Maintenance": "e.g. Service, tyres",
    "Vehicle Permits": "e.g. Permit renewal",
    "Diesel": "e.g. Fill on 12 Sep",
    "Travel": "e.g. Bus to Guntur",
    "Misc": "e.g. Stationery, impact driver, meeting snacks",
}


def month_key(d) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_label(mkey: str) -> str:
    try:
        return datetime.strptime(mkey, "%Y-%m").strftime("%b %Y")
    except Exception:
        return mkey


def normalize_reg_no(reg: str) -> str:
    """AP 16 AB-1234 / ap16ab1234 -> AP16AB1234, so one vehicle can't appear
    twice under slightly different spellings."""
    return "".join(ch for ch in str(reg).upper() if ch.isalnum())


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "1.0", "true", "yes")


def load_expenses() -> pd.DataFrame:
    df = get_data("Expenses")
    if df.empty:
        df = pd.DataFrame(columns=EXPENSE_COLS)
    df = df.copy()
    for c in EXPENSE_COLS:
        if c not in df.columns:
            df[c] = ""
    for c in ("amount", "rate_1ph", "rate_3ph"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def load_vehicles() -> pd.DataFrame:
    df = get_data("Vehicles")
    if df.empty:
        df = pd.DataFrame(columns=VEHICLE_COLS)
    df = df.copy()
    for c in VEHICLE_COLS:
        if c not in df.columns:
            df[c] = ""
    return df


def month_installs(df_inst: pd.DataFrame, mkey: str):
    """(1PH, 3PH) installs recorded in Installations for a calendar month."""
    if df_inst.empty or not has_col(df_inst, "date", "qty_1ph", "qty_3ph"):
        return 0, 0
    d = pd.to_datetime(df_inst["date"], errors="coerce")
    m = d.dt.strftime("%Y-%m") == mkey
    return int(safe_numeric_col(df_inst[m], "qty_1ph").sum()), int(safe_numeric_col(df_inst[m], "qty_3ph").sum())


def expense_summary(df_exp: pd.DataFrame, mkey: str, n_1ph: int, n_3ph: int) -> dict:
    """Fixed, variable and total cost for a month, and each per install.

    Per-install figures divide by ALL installs that month (1PH + 3PH).
    They are None when there are no installs, rather than a misleading 0."""
    rows = df_exp[df_exp["month"].astype(str) == mkey] if not df_exp.empty else df_exp
    fixed = rows[rows["cost_type"] == "Fixed"]
    var = rows[rows["cost_type"] == "Variable"]

    by_cat = []
    for cat in EXPENSE_FIXED_CATEGORIES:
        amt = float(fixed.loc[fixed["category"] == cat, "amount"].sum())
        if amt:
            by_cat.append(("Fixed", cat, amt))
    for cat in EXPENSE_VARIABLE_CATEGORIES:
        sub = var[var["category"] == cat]
        amt = float((sub["rate_1ph"] * n_1ph + sub["rate_3ph"] * n_3ph).sum())
        if amt or not sub.empty:
            by_cat.append(("Variable", cat, amt))

    fixed_total = float(fixed["amount"].sum())
    variable_total = float((var["rate_1ph"] * n_1ph + var["rate_3ph"] * n_3ph).sum())
    # Variable cost of one more install, used for the target projection and the
    # slider. 1PH rate only, as agreed — change to a mix here if 3PH is ever
    # to be projected too.
    variable_rate = float(var["rate_1ph"].sum())
    total_cost = fixed_total + variable_total
    n = n_1ph + n_3ph
    # None (shown as "—") when there are no installs to divide by, or no costs
    # entered for the month: 0.00 would read as "these installs cost nothing".
    per = (lambda x: x / n) if (n > 0 and not rows.empty) else (lambda x: None)
    return {
        "installs_1ph": n_1ph, "installs_3ph": n_3ph, "installs": n,
        "fixed_total": fixed_total, "variable_total": variable_total, "total_cost": total_cost,
        "variable_rate": variable_rate,
        "fixed_per_install": per(fixed_total), "variable_per_install": per(variable_total),
        "total_per_install": per(total_cost), "by_category": by_cat,
        "has_entries": not rows.empty,
    }


def cost_at_installs(fixed_total: float, variable_rate: float, n_installs: int) -> dict:
    """Cost per install at any install count, for the target projection and the
    slider.

    Fixed costs are taken as the FULL month's — rent, salaries and EMIs are
    monthly by nature, and diesel/misc are entered for the whole month — so
    they don't grow with more installs; only the variable rate does. That is
    the whole point of the curve: fixed cost per install falls as installs rise.
    """
    if n_installs <= 0:
        return {"installs": 0, "fixed_per_install": None, "variable_per_install": None,
                "total_per_install": None, "total_cost": fixed_total}
    fixed_pi = fixed_total / n_installs
    return {
        "installs": n_installs,
        "fixed_per_install": fixed_pi,
        "variable_per_install": variable_rate,
        "total_per_install": fixed_pi + variable_rate,
        "total_cost": fixed_total + variable_rate * n_installs,
    }


@st.fragment
def render_cost_slider(fixed_total: float, variable_rate: float, actual_installs: int, sel_month: str):
    """The install-count slider and its curve.

    A fragment: dragging reruns ONLY this section. Without it every drag
    re-executes all seven tabs — rebuilding the map's pins and the analytics
    tables each time — which made the slider feel sluggish and burned cache
    refreshes (and so quota) for nothing."""
    sub_hdr("gauge", "Cost At Any Install Count")
    slider_max = EXPENSE_SLIDER_MAX
    default_n = int(actual_installs or MONTHLY_TARGET)
    picked = st.slider("Installs in the month", min_value=0, max_value=slider_max,
                       value=min(default_n, slider_max), step=25, key=f"exp_slider_{sel_month}",
                       help="Drag to see how the cost per install changes with volume.")
    at_pick = cost_at_installs(fixed_total, variable_rate, picked)
    render_stat_tiles([
        ("bolt", f"{picked:,}", "Installs", "chosen", "normal"),
        ("wallet", fmt_rs(at_pick["fixed_per_install"], 1), "Fixed", "Rs./install", "normal"),
        ("gauge", fmt_rs(at_pick["variable_per_install"], 1), "Variable", "Rs./install", "normal"),
        ("target", fmt_rs(at_pick["total_per_install"], 1), "Total", "Rs./install", "normal"),
    ])
    st.markdown(
        f'<div class="info-box">At {picked:,} installs the month costs Rs. {at_pick["total_cost"]:,.0f}'
        + (f' — Rs. {at_pick["total_per_install"]:,.2f} per install.</div>'
           if at_pick["total_per_install"] is not None else ' — no installs to divide by.</div>'),
        unsafe_allow_html=True)

    # The curve behind the slider: fixed cost per install falls as volume
    # rises, while variable stays flat.
    pts = [x for x in range(100, slider_max + 1, max(25, slider_max // 40))]
    if pts:
        curve = pd.DataFrame(
            {"Total": [fixed_total / x + variable_rate for x in pts],
             "Fixed": [fixed_total / x for x in pts],
             "Variable": [variable_rate for x in pts]},
            index=pd.Index(pts, name="Installs in the month"))
        st.line_chart(curve, height=220)


def apply_expense_edits(df_exp: pd.DataFrame, edited: pd.DataFrame) -> pd.DataFrame:
    """Merge the Expenses tab's edit table back into the full Expenses sheet,
    matched by expense_id — other months' rows are never touched."""
    out = df_exp[EXPENSE_COLS].copy().set_index("expense_id")
    for _, r in edited.iterrows():
        eid = r["expense_id"]
        if eid not in out.index:
            continue
        if r["Delete"]:
            out = out.drop(index=eid)
            continue
        out.at[eid, "item"] = str(r["Description"] if pd.notna(r["Description"]) else "").strip()
        out.at[eid, "amount"] = float(r["Amount (Rs.)"] or 0)
        out.at[eid, "rate_1ph"] = float(r["Rate 1PH"] or 0)
        out.at[eid, "rate_3ph"] = float(r["Rate 3PH"] or 0)
        out.at[eid, "recurring"] = "1" if r["Repeats"] else "0"
    return out.reset_index()[EXPENSE_COLS]


def apply_vehicle_edits(edited: pd.DataFrame, used_regs: set):
    """Returns (vehicles_df, blocked_regs). A vehicle with costs on record is
    deactivated rather than deleted, so those costs keep their vehicle."""
    keep, blocked = [], []
    for _, r in edited.iterrows():
        reg = r["Registration No."]
        desc = str(r["Description"] if pd.notna(r["Description"]) else "").strip()
        if r["Delete"]:
            if reg in used_regs:
                blocked.append(reg)
                keep.append({"reg_no": reg, "description": desc, "is_active": "0"})
            continue
        keep.append({"reg_no": reg, "description": desc, "is_active": "1" if r["Active"] else "0"})
    return pd.DataFrame(keep, columns=VEHICLE_COLS), blocked


def fmt_rs(v, decimals: int = 0) -> str:
    return "—" if v is None else f"{v:,.{decimals}f}"

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
UNASSIGNED_SUPERVISOR = "Unassigned"

# ── Supervisors ────────────────────────────────────────────────────────────
# Supervisors live in their own sheet so they exist independently of any
# technician: you can create one before assigning anybody, and renaming one
# doesn't orphan existing mappings. Technicians.supervisor stores the stable
# supervisor_id, not the display name.
#   Supervisors sheet: supervisor_id, name, phone, is_active
sup_id_to_name = {}
sup_name_to_id = {}
if not df_supervisors_master.empty and has_col(df_supervisors_master, "supervisor_id", "name"):
    for _, r in df_supervisors_master.iterrows():
        sid = str(r.get("supervisor_id", "")).strip()
        snm = str(r.get("name", "")).strip()
        if sid and snm:
            sup_id_to_name[sid] = snm
            sup_name_to_id[snm] = sid


def resolve_supervisor_name(stored_value) -> str:
    """Technicians.supervisor holds a supervisor_id. Older rows (written before
    the Supervisors sheet existed) hold the supervisor's NAME instead, so fall
    back to matching on name rather than showing those as Unassigned."""
    v = str(stored_value).strip()
    if not v:
        return ""
    if v in sup_id_to_name:
        return sup_id_to_name[v]
    if v in sup_name_to_id:       # legacy row stored the name directly
        return v
    return v                       # unknown id/name — surface it as-is


# Installer LoginID -> supervisor display name.
login_to_supervisor = {}
if not df_technicians_master.empty and has_col(df_technicians_master, "login_id", "name"):
    for _, r in df_technicians_master.iterrows():
        lid = str(r.get("login_id", "")).strip()
        nm = str(r.get("name", "")).strip()
        sup_raw = str(r.get("supervisor", "")).strip() if "supervisor" in df_technicians_master.columns else ""
        if lid and nm:
            tech_login_lookup[lid.lower()] = nm
            name_to_login_id[nm] = lid
            sup_name = resolve_supervisor_name(sup_raw)
            if sup_name:
                login_to_supervisor[lid.lower()] = sup_name

# Active supervisors, for the Analytics filter and Admin dropdowns.
known_supervisors = sorted([
    nm for sid, nm in sup_id_to_name.items()
    if str(df_supervisors_master.loc[df_supervisors_master["supervisor_id"] == sid, "is_active"].iloc[0]).strip().lower() in ("1", "1.0", "true", "yes", "")
] if not df_supervisors_master.empty and "is_active" in df_supervisors_master.columns else list(sup_id_to_name.values()))
# Any supervisor names referenced by technicians but missing from the sheet
# still need to appear, or those technicians would silently drop out of filters.
known_supervisors = sorted(set(known_supervisors) | set(login_to_supervisor.values()))


def supervisor_of(installer_id) -> str:
    return login_to_supervisor.get(str(installer_id).strip().lower(), UNASSIGNED_SUPERVISOR)


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

    # Every record in this batch belongs on the map — not only the brand-new
    # ones. Records already in the install log (pushed before MapRecords
    # existed, or when a mirror write failed) were otherwise never mirrored,
    # because the paths below that find "nothing new" returned before the
    # mirror ran. The mirror is an upsert, so re-sending known rows is safe.
    map_batch = []
    for rec in parsed_records:
        tn = tech_login_lookup.get(str(rec["installer_id"]).lower(), rec["installer_id"])
        map_batch.append({
            "key": f"{rec['date']}||{rec['time']}||{rec['installer_id']}",
            "date": rec["date"], "time": rec["time"], "installer_id": rec["installer_id"],
            "tech_name": tn, "location": rec.get("location") or "",
            "sno": rec.get("sno") or "", "old_meter_no": rec.get("old_meter_no") or "",
            "new_meter_no": rec.get("new_meter_no") or "",
            "lat": rec.get("lat") or "", "long": rec.get("long") or "",
        })

    fully_dup_dates = dates_seen - dates_with_new

    if not new_log_rows and not backfilled_count:
        map_changed, map_ok = mirror_records_to_map(map_batch)
        if map_changed:
            st.success(f"✅ Installs were already recorded — added/updated {map_changed} record(s) on the Map.")
            st.rerun()
        st.info(f"Installs for {', '.join(sorted(dates_seen))} are already recorded and already on the Map.")
        return

    # 1) append/update raw log rows (dedup + detail ledger)
    updated_log = pd.concat([df_log_existing, pd.DataFrame(new_log_rows)], ignore_index=True) if new_log_rows else df_log_existing

    if not new_log_rows:
        if safe_update("UploadedInstallLog", updated_log):
            mirror_records_to_map(map_batch)
            st.success(f"✅ No new installs, but filled in missing details for {backfilled_count} existing record(s).")
            st.rerun()
        return

    # 2) aggregate the NEW rows only, by date + tech_name + location
    new_log_df = pd.DataFrame(new_log_rows)
    _phase = new_log_df["meter_type"].apply(classify_meter_type)
    new_log_df["is_1ph"] = _phase == "1PH"
    new_log_df["is_3ph"] = _phase == "3PH"
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
        map_added, map_ok = mirror_records_to_map(map_batch)
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
    key_to_idx = {k: i for i, k in zip(df_map_existing.index, df_map_existing["key"].values)}

    def _blank(v):
        return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "nan", "Unspecified")

    new_map_rows = []
    filled = 0
    for rec in records:
        key = rec.get("key") or f"{rec.get('date')}||{rec.get('time')}||{rec.get('installer_id')}"
        if key in key_to_idx:
            # Upsert, not skip. A map row can exist with no coordinates (it was
            # mirrored before the Analytics file carrying lat/long arrived);
            # skipping it outright left that pin off the map permanently.
            idx = key_to_idx[key]
            changed = False
            for col in map_cols:
                if col == "key":
                    continue
                new_val = rec.get(col)
                if not _blank(new_val) and _blank(df_map_existing.at[idx, col]):
                    df_map_existing.at[idx, col] = str(new_val)
                    changed = True
            filled += int(changed)
            continue
        row = {col: rec.get(col, "") for col in map_cols}
        row["key"] = key
        key_to_idx[key] = None
        new_map_rows.append(row)

    if not new_map_rows and not filled:
        return 0, True
    updated_map = (pd.concat([df_map_existing, pd.DataFrame(new_map_rows)], ignore_index=True)
                   if new_map_rows else df_map_existing)
    ok = safe_update("MapRecords", updated_map)
    return len(new_map_rows) + filled, ok


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

    # Cause, from the data rather than a guess: how much of each row's extra
    # the old 1PH/3PH rule would have added (installs whose meter type holds
    # both a 1 and a 3). If the fix has already been applied, none of it is.
    if not flagged.empty and has_col(df_log, "meter_type"):
        both = df_log["meter_type"].apply(lambda s: int(("1" in str(s)) and ("3" in str(s))))
        both_counts = df_log.assign(_b=both).groupby(["date", "tech_name", "location"])["_b"].sum()
        phase_fixed = bool(str(get_setting("phase_fix_applied", "")).strip())

        def _cause(r):
            explained = 0 if phase_fixed else int(both_counts.get((r["date"], r["tech_name"], r["location"]), 0))
            extra = int(r["Implied Manual Qty"])
            if explained >= extra:
                return "1PH/3PH double count"
            if explained > 0:
                return f"{explained} double count + {extra - explained} other"
            return "Not in uploads (manual entry or repeat push)"
        flagged["Likely cause"] = flagged.apply(_cause, axis=1)
    else:
        flagged["Likely cause"] = "Not in uploads (manual entry or repeat push)"

    return flagged[["date", "tech_name", "location", "Installations Qty", "Upload-Derived Qty",
                    "Implied Manual Qty", "Likely cause"]].rename(
        columns={"date": "Date", "tech_name": "Technician", "location": "Location"}
    ).sort_values("Implied Manual Qty", ascending=False)


def reduce_rows_to_upload_counts(keys) -> int:
    """For each flagged (date, technician, location), set that Installations
    row to exactly what its uploaded records support — correctly split into
    1PH / 3PH. Removes only the EXTRA on top of the uploads; the uploaded
    installs themselves stay. Returns the number of rows changed."""
    df_inst = get_data("Installations")
    df_log = get_data("UploadedInstallLog")
    if df_inst.empty or df_log.empty or not keys:
        return 0
    df_inst = df_inst.copy()
    for col in ("qty_1ph", "qty_3ph"):
        df_inst[col] = pd.to_numeric(df_inst[col], errors="coerce").fillna(0).astype(int)
    phase = df_log["meter_type"].apply(classify_meter_type) if "meter_type" in df_log.columns else pd.Series("", index=df_log.index)
    log = df_log.assign(_1=(phase == "1PH").astype(int), _3=(phase == "3PH").astype(int))
    truth = log.groupby(["date", "tech_name", "location"])[["_1", "_3"]].sum()

    changed = 0
    for d, t, l in keys:
        if (d, t, l) not in truth.index:
            continue
        want_1, want_3 = (int(x) for x in truth.loc[(d, t, l)])
        m = ((df_inst["date"].astype(str) == str(d)) & (df_inst["tech_name"].astype(str) == str(t))
             & (df_inst["location"].astype(str) == str(l)))
        # Only rows that exceed the uploads — a separate, smaller manual row
        # for the same day is a different entry and is left alone.
        m &= (df_inst["qty_1ph"] + df_inst["qty_3ph"]) > (want_1 + want_3)
        for idx in df_inst[m].index:
            df_inst.at[idx, "qty_1ph"] = want_1
            df_inst.at[idx, "qty_3ph"] = want_3
            changed += 1
    if changed and safe_update("Installations", df_inst):
        return changed
    return 0


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
    out = dups[cols].rename(columns={
        "key": "Key", "sno": "SNO", "date": "Date", "time": "Time", "tech_name": "Technician",
        "location": "Location", "meter_type": "Meter Type", "old_meter_no": "Old Meter No", "new_meter_no": "New Meter No",
    })
    for _idc in ["SNO", "Old Meter No", "New Meter No"]:
        if _idc in out.columns:
            out[_idc] = out[_idc].apply(clean_id_value)
    return out


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
    out = near[cols].rename(columns={
        "key": "Key", "installer_id": "Installer LoginID", "tech_name": "Technician", "date": "Date",
        "time": "Time", "location": "Location", "sno": "SNO", "meter_type": "Meter Type",
    })
    if "SNO" in out.columns:
        out["SNO"] = out["SNO"].apply(clean_id_value)
    return out


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
        _phase = removed_rows["meter_type"].apply(classify_meter_type)
        removed_rows["is_1ph"] = _phase == "1PH"
        removed_rows["is_3ph"] = _phase == "3PH"
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
    out = dups[cols].rename(columns={
        "key": "Key", "sno": "SNO", "date": "Date", "time": "Time", "tech_name": "Technician",
        "location": "Location", "old_meter_no": "Old Meter No", "new_meter_no": "New Meter No",
    })
    for _idc in ["SNO", "Old Meter No", "New Meter No"]:
        if _idc in out.columns:
            out[_idc] = out[_idc].apply(clean_id_value)
    return out


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


def _old_phase_flags(mt):
    """The retired rule, kept ONLY to work out what it added to Installations."""
    s = str(mt)
    return ("1" in s), ("3" in s)


def plan_phase_count_repair():
    """Work out the correction needed to Installations for installs counted
    under the old digit-matching rule. Returns (per_group_df, per_value_df).

    Every row in UploadedInstallLog was added to Installations by the old rule,
    so for each date/technician/location the exact overcount is
        (old 1PH, old 3PH) - (correct 1PH, correct 3PH).
    Applying that difference removes only the misclassification; any manually
    entered quantity on the same row is left exactly as it was."""
    log = get_data("UploadedInstallLog")
    if log.empty or not has_col(log, "date", "tech_name", "location", "meter_type"):
        return pd.DataFrame(), pd.DataFrame()
    log = log.copy()
    old = log["meter_type"].apply(_old_phase_flags)
    log["old_1"] = old.apply(lambda t: int(t[0]))
    log["old_3"] = old.apply(lambda t: int(t[1]))
    new = log["meter_type"].apply(classify_meter_type)
    log["new_1"] = (new == "1PH").astype(int)
    log["new_3"] = (new == "3PH").astype(int)

    g = log.groupby(["date", "tech_name", "location"])[["old_1", "old_3", "new_1", "new_3"]].sum().reset_index()
    g["d_1ph"] = g["new_1"] - g["old_1"]
    g["d_3ph"] = g["new_3"] - g["old_3"]
    g = g[(g["d_1ph"] != 0) | (g["d_3ph"] != 0)]

    vals = log.groupby("meter_type").agg(Installs=("date", "size"), old_1=("old_1", "max"), old_3=("old_3", "max")).reset_index()
    def _was(r):
        if r.old_1 and r.old_3: return "1PH + 3PH (counted twice)"
        return "1PH" if r.old_1 else ("3PH" if r.old_3 else "not counted")
    vals["Counted before"] = vals.apply(_was, axis=1)
    vals["Counted now"] = vals["meter_type"].apply(lambda v: classify_meter_type(v) or "not counted")
    vals = vals.rename(columns={"meter_type": "Meter type"})[["Meter type", "Installs", "Counted before", "Counted now"]]
    return g, vals.sort_values("Installs", ascending=False)


def apply_phase_count_repair(plan: pd.DataFrame) -> int:
    df = get_data("Installations")
    if df.empty or plan.empty:
        return 0
    df = df.copy()
    for col in ("qty_1ph", "qty_3ph"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    touched = 0
    for _, p in plan.iterrows():
        m = ((df["date"].astype(str) == str(p["date"])) &
             (df["tech_name"].astype(str) == str(p["tech_name"])) &
             (df["location"].astype(str) == str(p["location"])))
        if not m.any():
            continue
        idx = df[m].index[0]
        # Never below the correct upload count. If this row was already reset
        # by "Remove extra" in the discrepancy check, the overcount is already
        # gone — applying the delta again would subtract real installs. The
        # floor makes the two tools safe to use in either order.
        df.at[idx, "qty_1ph"] = max(int(p["new_1"]), int(df.at[idx, "qty_1ph"]) + int(p["d_1ph"]))
        df.at[idx, "qty_3ph"] = max(int(p["new_3"]), int(df.at[idx, "qty_3ph"]) + int(p["d_3ph"]))
        touched += 1
    if touched and safe_update("Installations", df):
        return touched
    return 0


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
                _phase = bad_rows["meter_type"].apply(classify_meter_type)
                bad_rows["is_1ph"] = _phase == "1PH"
                bad_rows["is_3ph"] = _phase == "3PH"
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


def render_meter_search(key_prefix: str = "inst", show_heading: bool = True):
    """Search By Meter / Service No. Used both in the Installs tab and in the
    header's quick-search, so there is only one copy to keep correct."""
    if show_heading:
        sec_hdr("search", "Search By Meter / Service No")
    search_query = st.text_input("Search SNO / Old Meter No / New Meter No", key=f"{key_prefix}_meter_search_box",
                                 placeholder="e.g. 1234567890 or meter serial number",
                                 label_visibility="visible" if show_heading else "collapsed")

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
                results_display = results[cols_present].rename(columns=display_cols_map).copy()
                for _idc in ["SNO", "Old Meter No", "New Meter No"]:
                    if _idc in results_display.columns:
                        results_display[_idc] = results_display[_idc].apply(clean_id_value)
                st.success(f"✅ Found {len(results)} match(es).")
                st.dataframe(results_display, use_container_width=True, hide_index=True,
                             height=dataframe_height(len(results_display), max_px=500))

                # Label: value text, so a result can be pasted into WhatsApp or
                # a ticket without the receiver needing the app.
                blocks = []
                for i, (_, row) in enumerate(results_display.iterrows(), 1):
                    lines = [f"--- Result {i} of {len(results_display)} ---"] if len(results_display) > 1 else []
                    lines += [f"{col}: {row[col]}" for col in results_display.columns if str(row[col]).strip()]
                    blocks.append("\n".join(lines))
                export_text = "\n\n".join(blocks)

                st.text_area("Copy as text", export_text, height=170, key=f"{key_prefix}_search_export_text",
                             help="Tap inside, select all, copy — or use Download below.")
                dl1, dl2 = st.columns(2)
                with dl1:
                    st.download_button("Download as text", data=export_text,
                                       file_name=f"search_{search_query.strip()[:20] or 'results'}.txt",
                                       mime="text/plain", use_container_width=True, key=f"{key_prefix}_search_dl_txt", on_click="ignore")
                with dl2:
                    st.download_button("Download as CSV", data=results_display.to_csv(index=False),
                                       file_name=f"search_{search_query.strip()[:20] or 'results'}.csv",
                                       mime="text/csv", use_container_width=True, key=f"{key_prefix}_search_dl_csv", on_click="ignore")


# ── Persistent Map-sync failure warning (survives the st.rerun() that would ──
# otherwise wipe it — see mirror_records_to_map) ─────────────────────────────
if "map_sync_warning" in st.session_state:
    with _notice_area:
        st.markdown(f'<div class="danger-box">{st.session_state["map_sync_warning"]}</div>', unsafe_allow_html=True)
        if st.button("✅ Got it, dismiss", key="dismiss_map_sync_warning"):
            del st.session_state["map_sync_warning"]
            st.rerun()
        st.divider()


# ── Pending double-count confirmation banner (rendered before the tabs so ──
# it's visible no matter which tab triggered it) ────────────────────────────
if "pending_push" in st.session_state:
    with _notice_area:
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


# Quick search in the header — rendered into the column reserved beside the
# banner, now that the data connection is ready.
with head_search:
    with st.popover("🔍", use_container_width=True, help="Search by meter / service no"):
        render_meter_search("hdr", show_heading=False)

# ── Tabs Configuration ────────────────────────────────────────────────────────
# Plain labels — the design system uses no emoji as interface icons, and they
# render differently on every device.
tab_dash, tab_analytics, tab_map, tab_exp, tab_liaison, tab_inst, tab_inv, tab_admin = st.tabs([
    "Dashboard", "Analytics", "Map", "Expenses", "Liaisoning", "Installs", "Store", "Admin"
])

# ═══════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dash:
    tab_action_bar("dash")
    df_inst = df_installations_master
    df_inv = df_inventory_master

    sec_hdr("calendar", "Monthly Installs Overview")

    if df_inst.empty or not has_col(df_inst, "date", "qty_1ph", "qty_3ph", "location"):
        st.info("No installation data yet.")
    else:
        df_month = df_inst.copy()
        df_month["_date"] = pd.to_datetime(df_month["date"], errors="coerce")
        df_month["qty_1ph"] = safe_numeric_col(df_month, "qty_1ph")
        df_month["qty_3ph"] = safe_numeric_col(df_month, "qty_3ph")

        today = today_ist()
        this_month = df_month[(df_month["_date"].dt.month == today.month) & (df_month["_date"].dt.year == today.year)]

        m_1ph = int(this_month["qty_1ph"].sum())
        m_3ph = int(this_month["qty_3ph"].sum())
        m_total = m_1ph + m_3ph

        # HeroStat measures against the monthly TARGET (set in Admin), not
        # against stock received — stock on hand says nothing about whether
        # the month is on course.
        # Days remaining are counted from the last date that actually has
        # installs recorded, so a day already counted in m_total is not also
        # counted as a day still available.
        last_install_dt = this_month["_date"].max() if not this_month.empty else None
        last_install_date = last_install_dt.date() if pd.notna(last_install_dt) else None
        tgt = monthly_target_status(m_total, MONTHLY_TARGET, today, last_install_date)
        render_hero_stat(
            "THIS MONTH · INSTALLS VS TARGET",
            f"{m_total:,} / {MONTHLY_TARGET:,}",
            f"{tgt['pct']:.0f}% of target · {tgt['days_left']} working day(s) left",
            tgt["pct"],
        )

        render_stat_tiles([
            ("bolt", f"{m_1ph:,}", "1PH", "month", "normal"),
            ("bolt", f"{m_3ph:,}", "3PH", "month", "normal"),
            ("target", f"{tgt['remaining']:,}", "Still", "to go", "normal"),
            ("gauge", f"{tgt['per_day_needed']:.0f}", "Need", "per day",
             "normal" if tgt["on_track"] else "danger"),
        ])
        sub_hdr("rupee", "This Month — 1PH Billing")
        month_1ph_count = m_1ph
        billing = calculate_1ph_incentive_billing(month_1ph_count)
        # Running cost per install for the same month, from the Expenses tab —
        # beside the billed rate so the two can be compared at a glance.
        month_cost = expense_summary(load_expenses(), month_key(today), m_1ph, m_3ph)
        tb1, tb2, tb3 = st.columns(3)
        tb1.metric("Total Billing (Rs.)", f"{billing['total_cost']:,.0f}")
        tb2.metric("Blended Cost / Install (Rs.)", f"{billing['blended_per_install']:,.2f}" if month_1ph_count > 0 else "—")
        tb3.metric("Total Cost / Install (Rs.)", fmt_rs(month_cost["total_per_install"], 2),
                   help="This month's fixed + variable costs from the Expenses tab, divided by all installs this month (1PH + 3PH).")
        with st.expander("View slab breakdown"):
            slab_df = pd.DataFrame(billing["slabs"])
            if not slab_df.empty:
                st.dataframe(slab_df, use_container_width=True, hide_index=True)
            cb1, cb2, cb3 = st.columns(3)
            cb1.metric("Base Cost (Rs.)", f"{billing['base_cost']:,.0f}")
            cb2.metric("Tiered Incentive (Rs.)", f"{billing['tier_incentive']:,.0f}")
            cb3.metric("Survey (Rs.)", f"{billing['flat_addon']:,.0f}")

        sub_hdr("pin", "This Month, By Location")
        if this_month.empty:
            st.info("No installs recorded this month yet.")
        else:
            loc_month = this_month.groupby("location")[["qty_1ph", "qty_3ph"]].sum().reset_index()
            loc_month["Total"] = loc_month["qty_1ph"] + loc_month["qty_3ph"]
            loc_month.columns = ["Location", "1PH", "3PH", "Total"]
            for _qc in ["1PH", "3PH", "Total"]:
                loc_month[_qc] = loc_month[_qc].astype(int)
            loc_month = loc_month.sort_values("Total", ascending=False)
            render_count_cards(
                [(r["Location"], int(r["Total"])) for _, r in loc_month.iterrows()],
                columns=3, total_label="Month total",
            )
            with st.expander("View as table (1PH / 3PH split)"):
                st.dataframe(loc_month, use_container_width=True, hide_index=True)
                download_image_button(loc_month, "This_Month_By_Location.png", key="dl_img_loc_month", title="This Month, By Location")

    st.divider()
    sec_hdr("box", "Live Inventory Stock")

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

    render_stat_tiles([
        ("bolt",  f"{int(total_in_1ph):,}", "Recv", "1PH", "normal"),
        ("bolt",  f"{int(total_in_3ph):,}", "Recv", "3PH", "normal"),
        ("alert" if pending_1ph < 0 else "bolt", f"{pending_1ph:,}", "Pend", "1PH",
         "danger" if pending_1ph < 0 else "normal"),
        ("alert" if pending_3ph < 0 else "bolt", f"{pending_3ph:,}", "Pend", "3PH",
         "danger" if pending_3ph < 0 else "normal"),
    ])
    if pending_1ph < 0 or pending_3ph < 0:
        deficits = [t for t, v in (("1PH", pending_1ph), ("3PH", pending_3ph)) if v < 0]
        st.markdown(f'<div class="danger-box">More {" and ".join(deficits)} meters installed than received — check Inventory entries.</div>', unsafe_allow_html=True)

    # ── Monthly Installs Overview ────────────────────────────────────────────
    st.divider()
    sec_hdr("plug", "Installation Summary")

    if df_inst.empty or not has_col(df_inst, "date", "tech_name", "location", "qty_1ph", "qty_3ph"):
        st.info("No installation data yet. Add entries in the Installs tab.")
    else:
        f1, f2 = st.columns(2)
        with f1:
            date_range = st.date_input("Date Range", [today_ist(), today_ist()])
        with f2:
            meter_filter = st.multiselect("Meter Type", ["1 PH", "3 PH"], default=["1 PH", "3 PH"])

        if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
            d_start, d_end = date_range[0], date_range[1]
        elif isinstance(date_range, (list, tuple)) and len(date_range) == 1:
            d_start = d_end = date_range[0]
        else:
            d_start = d_end = date_range

        show_1ph, show_3ph = "1 PH" in meter_filter, "3 PH" in meter_filter

        # Work out what was actually installed in the chosen dates FIRST, so
        # the Location and Technician lists only offer people and places with
        # installs in that range. Previously both lists came from all data
        # ever recorded, so long-idle installers still appeared.
        in_range = df_inst.copy()
        in_range["_date"] = pd.to_datetime(in_range["date"], errors="coerce").dt.date
        in_range = in_range[(in_range["_date"] >= d_start) & (in_range["_date"] <= d_end)]
        in_range["qty_1ph"] = safe_numeric_col(in_range, "qty_1ph")
        in_range["qty_3ph"] = safe_numeric_col(in_range, "qty_3ph")
        # "Did installs" respects the meter-type filter too: with only 3PH
        # selected, someone who fitted only 1PH meters did no relevant work.
        in_range["_qty"] = (in_range["qty_1ph"] if show_1ph else 0) + (in_range["qty_3ph"] if show_3ph else 0)
        active = in_range[in_range["_qty"] > 0]

        loc_list = sorted([l for l in active["location"].astype(str).unique() if l.strip()])

        f3, f4 = st.columns(2)
        with f3:
            loc_filter = st.multiselect("Locations", loc_list, default=loc_list)
        # Technicians narrow to the chosen locations as well, so nobody is
        # listed who didn't install in the places being looked at.
        active_scoped = active[active["location"].isin(loc_filter)] if loc_filter else active
        tech_list = sorted([t for t in active_scoped["tech_name"].astype(str).unique() if t.strip()])
        with f4:
            tech_filter = st.multiselect("Technicians", tech_list, default=tech_list)

        # No message when the chosen dates hold nothing: the filters and totals
        # already read zero, and today is empty every morning until the day's
        # file is uploaded.

        filtered = in_range
        if loc_filter:
            filtered = filtered[filtered["location"].isin(loc_filter)]
        if tech_filter:
            filtered = filtered[filtered["tech_name"].isin(tech_filter)]
        sum_1ph = int(filtered["qty_1ph"].sum()) if show_1ph else 0
        sum_3ph = int(filtered["qty_3ph"].sum()) if show_3ph else 0

        m1, m2, m3 = st.columns(3)
        m1.metric("Filtered 1PH", sum_1ph)
        m2.metric("Filtered 3PH", sum_3ph)
        m3.metric("Grand Total", sum_1ph + sum_3ph)

        if not filtered.empty:
            sec_hdr("users", "Technician Breakdown")
            group_df = filtered.groupby(["tech_name", "location"])[["qty_1ph", "qty_3ph"]].sum().reset_index()
            group_df["Total"] = group_df["qty_1ph"] + group_df["qty_3ph"]
            # Same rule as the filters: no card for a technician/location with
            # nothing installed in these dates.
            group_df = group_df[group_df["Total"] > 0]
            group_df.columns = ["Technician", "Location", "1PH", "3PH", "Total"]
            # Counts are whole meters — the upstream to_numeric leaves them as
            # floats, which renders as "12.0".
            for _qc in ["1PH", "3PH", "Total"]:
                group_df[_qc] = group_df[_qc].astype(int)
            group_df = group_df.sort_values("Total", ascending=False)
            st.caption(f"{len(group_df)} technician(s) · sorted by total")
            # Two-up card grid rather than one row each: at 30-50 technicians a
            # full-width list is a scroll marathon, and the fix is arrangement,
            # not smaller type.
            render_technician_cards(
                [(r["Technician"], r["Location"], int(r["Total"])) for _, r in group_df.iterrows()],
                INSTALLER_TOTAL_RED_MAX, INSTALLER_TOTAL_YELLOW_MAX,
            )
            with st.expander("View as table (1PH / 3PH split)"):
                st.dataframe(group_df, use_container_width=True, hide_index=True,
                             height=dataframe_height(len(group_df)))
            download_image_button(
                group_df, "Technician_Breakdown.png", key="dl_img_group_df",
                color_grid=build_single_col_color_grid(group_df, "Total", lambda v: tier_colors(v, INSTALLER_TOTAL_RED_MAX, INSTALLER_TOTAL_YELLOW_MIN, INSTALLER_TOTAL_YELLOW_MAX)),
                title="Technician Breakdown",
            )

            sec_hdr("download", "Export & Share")
            export_df = group_df.copy()
            export_df.loc[len(export_df)] = ["---", "---", "---", "---", "---"]
            export_df.loc[len(export_df)] = ["GRAND TOTAL", "", sum_1ph, sum_3ph, sum_1ph + sum_3ph]
            export_df.loc[len(export_df)] = ["PENDING STOCK", "", pending_1ph, pending_3ph, ""]

            csv_data = export_df.to_csv(index=False).encode("utf-8")
            st.download_button("📥 Download CSV Report", data=csv_data, file_name="Installation_Summary.csv", mime="text/csv", use_container_width=True, on_click="ignore")

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
    sec_hdr("file", "Customer Report")

    rf1, rf2 = st.columns(2)
    with rf1:
        report_date_range = st.date_input("Date Range", [today_ist() - timedelta(days=6), today_ist()], key="report_date_range")
    with rf2:
        report_meter_type = st.selectbox("Meter Type", ["All", "1 PH", "3 PH"], key="report_meter_type")

    df_log_for_report = get_data("UploadedInstallLog")

    # Two levels: Section = the named Location (e.g. CHITTINAGAR); Section Code
    # = the 2-digit code from the SNO, several of which sit under one Location.
    all_locations = (
        sorted([l for l in df_log_for_report["location"].astype(str).str.strip().unique() if l and l != "Unspecified"])
        if not df_log_for_report.empty and "location" in df_log_for_report.columns else []
    )
    rf3, rf4 = st.columns(2)
    with rf3:
        report_locations = st.multiselect("Section (all if none picked)", all_locations, key="report_locations")

    # Codes offered are limited to the chosen Sections, so you can't pick a
    # combination that returns nothing.
    scoped = df_log_for_report
    if report_locations and not scoped.empty and "location" in scoped.columns:
        scoped = scoped[scoped["location"].astype(str).str.strip().isin(report_locations)]
    all_section_codes = sorted(scoped["sno"].apply(extract_section_code).unique()) if not scoped.empty and "sno" in scoped.columns else []
    with rf4:
        report_sections = st.multiselect("Section Code (all if none picked)", all_section_codes, key="report_sections")

    if not df_log_for_report.empty and "sno" in df_log_for_report.columns:
        codes = df_log_for_report["sno"].apply(extract_section_code)
        unclassified_n = int((codes == "Unclassified").sum())
        if unclassified_n:
            sample = df_log_for_report.loc[codes == "Unclassified", "sno"].astype(str).head(3).tolist()
            st.warning(f"⚠️ {unclassified_n} record(s) have an unreadable Consumer No and can't be assigned a section code. Examples: {', '.join(repr(s) for s in sample)}")

    if st.button("Generate Report", type="primary", use_container_width=True, key="generate_weekly_report_btn"):
        if isinstance(report_date_range, (list, tuple)) and len(report_date_range) == 2:
            rd_start, rd_end = report_date_range
        elif isinstance(report_date_range, (list, tuple)) and len(report_date_range) == 1:
            rd_start = rd_end = report_date_range[0]
        else:
            rd_start = rd_end = report_date_range
        with st.spinner("Generating report..."):
            pdf_bytes, err = build_weekly_report_pdf(
                rd_start, rd_end,
                section_filter=report_sections or None,
                meter_type_filter=report_meter_type,
                location_filter=report_locations or None,
            )
        if err:
            st.error(f"❌ {err}")
        else:
            st.session_state["weekly_report_pdf"] = pdf_bytes
            st.session_state["weekly_report_name"] = f"Weekly_Report_{rd_start}_to_{rd_end}.pdf"
            st.success("✅ Report ready below.")

    if "weekly_report_pdf" in st.session_state:
        st.download_button("Download Report (PDF)", data=st.session_state["weekly_report_pdf"],
                            file_name=st.session_state["weekly_report_name"], mime="application/pdf",
                            use_container_width=True, key="download_weekly_report", on_click="ignore")

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
        # Rewind first — the same upload object may already have been read once
        # this run (auto-process, then a manual retry), and a consumed stream
        # would fail to open the second time.
        try:
            analytics_file.seek(0)
        except Exception:
            pass
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
    tab_action_bar("analytics", show_upload=True)

    sec_hdr("upload", "Upload Progress File")
    up_col, go_col = st.columns([6, 1], vertical_alignment="center")
    with up_col:
        analytics_file = st.file_uploader(
            "MDM export (.xlsx)", type=["xlsx"], key="analytics_uploader",
            label_visibility="collapsed",
        )
    with go_col:
        # GO re-runs "Add & Process" on demand. New files still process
        # automatically on upload; GO is for a retry or a forced re-run.
        go_clicked = st.button("GO", type="primary", use_container_width=True,
                               key="analytics_go", disabled=analytics_file is None,
                               help="Add & process this file")

    SLOW_PROCESS_SECONDS = 5

    if analytics_file is not None:
        # Hash the actual bytes rather than name+size: the MDM export keeps the
        # same filename every day, and two different days' files can coincide
        # on size — which would make a genuinely new upload look "already
        # processed" and silently skip it.
        _fp_bytes = analytics_file.getvalue()
        file_fp = hashlib.sha256(_fp_bytes).hexdigest()[:16]
        analytics_file.seek(0)

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
            st.warning(("⚠️ Automatic processing failed — tap GO to retry." if not last_ok
                        else "⏳ Processing took a while — tap GO if the figures below don't look up to date."))

        if go_clicked:
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

        # Display order is glance -> "work until" -> date/supervisor, but the
        # logic needs the reverse: the pickers decide which installs the glance
        # counts. So reserve the three spots in display order now, and fill
        # them below in the order the logic needs.
        sec_hdr("target", "Today At A Glance")
        glance_slot = st.container()
        until_slot = st.container()
        picker_slot = st.container()

        with picker_slot:
            vc1, vc2 = st.columns(2)
            with vc1:
                sel_date = st.selectbox("Viewing date", avail_dates, index=0)
            day_df = df_araw[df_araw["date"] == sel_date].copy()
            day_df["hour_int"] = pd.to_numeric(day_df["hour"], errors="coerce")
            day_df["supervisor"] = day_df["installer_id"].apply(supervisor_of)

            # Supervisor scope: every figure below (glance, forecast, hourly,
            # half-day, pace) reflects the selection, so a supervisor can read the
            # tab as if it were only their own team.
            sups_today = sorted(day_df["supervisor"].unique())
            with vc2:
                sel_supervisor = st.selectbox("Supervisor", ["All supervisors"] + sups_today, key="analytics_supervisor")
            # Unscoped copy for the Installs push: the supervisor filter is a VIEW
            # choice, and must never decide which installs get recorded.
            day_df_all = day_df.copy()
            if sel_supervisor != "All supervisors":
                day_df = day_df[day_df["supervisor"] == sel_supervisor]

            # (No empty-guard needed: sups_today is derived from day_df itself, so
            # selecting any listed supervisor always leaves at least one record.)
            installers = sorted(day_df["installer_id"].unique())
            if UNASSIGNED_SUPERVISOR in sups_today and sel_supervisor == "All supervisors":
                unassigned_ids = sorted(day_df.loc[day_df["supervisor"] == UNASSIGNED_SUPERVISOR, "installer_id"].unique())
                st.caption(f"⚠️ Not mapped to a supervisor: {', '.join(unassigned_ids)} — set their Supervisor in Admin → Technicians.")

        with until_slot:
            day_end_choice = st.selectbox(
                "Assume work continues until", ["17:00", "18:00", "19:00", "20:00", "21:00"],
                index=1, key="forecast_day_end",
                help="Used only for the forecast. If installs are still coming in past this time, the forecast extends automatically.",
            )
        forecast_total, rate_per_hour, effective_end = (
            forecast_total_installs(day_df, installers, f"{day_end_choice}:00")
            if installers else (None, 0.0, f"{day_end_choice}:00")
        )
        with glance_slot:
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
                extended = effective_end[:5] != day_end_choice
                note = f" (extended past {day_end_choice} — installs still coming in)" if extended else ""
                st.caption(f"Projected to {effective_end[:5]} at the current team rate of {rate_per_hour:.0f} installs/hour{note}.")
            else:
                st.caption("Not enough data yet to project.")

        # -- Hourly table --------------------------------------------------
        # One header for every Analytics image export — the same figures as the
        # glance cards above, including the forecast — so all shared images
        # carry an identical, self-explanatory header.
        _scope_txt = "All supervisors" if sel_supervisor == "All supervisors" else f"Supervisor: {sel_supervisor}"
        analytics_img_meta = (
            f"{_scope_txt}   |   Last install: {str(max(day_df['time']))[:5]}\n"
            f"Total: {len(day_df)}   |   Active Installers: {len(installers)}   |   "
            f"Avg/Installer: {round(len(day_df) / len(installers), 1) if installers else 0}   |   "
            f"Forecast by {effective_end[:5]}: {forecast_total if forecast_total is not None else 'N/A'}"
        )

        sec_hdr("clock", "Installer-Wise Hourly Count")
        if day_df["hour_int"].notna().any():
            hr_min = int(day_df["hour_int"].min())
            hr_max = int(day_df["hour_int"].max())
        else:
            hr_min, hr_max = 8, 18

        hour_cols = list(range(hr_min, hr_max + 1))

        def _hour_row(label, sub):
            row = {"Installer": label}
            for h in hour_cols:
                row[f"{h}-{h+1}"] = int((sub["hour_int"] == h).sum())
            row["Total"] = len(sub)
            return row

        hour_col_labels = [f"{h}-{h+1}" for h in hour_cols]
        last_install_time = max(day_df["time"]) if not day_df.empty else "—"

        def _build_hourly_df(scope_df):
            """Per-installer rows for a scope, plus its own TOTAL row."""
            rows = [
                _hour_row(inst, scope_df[scope_df["installer_id"] == inst])
                for inst in scope_df.groupby("installer_id").size().sort_values(ascending=False).index
            ]
            hdf = pd.DataFrame(rows)
            tot = {"Installer": "TOTAL"}
            for h in hour_cols:
                tot[f"{h}-{h+1}"] = int(hdf[f"{h}-{h+1}"].sum())
            tot["Total"] = int(hdf["Total"].sum())
            return pd.concat([hdf, pd.DataFrame([tot])], ignore_index=True)

        hourly_view_mode = st.radio(
            "Hourly table view", ["📋 Table", "🔲 Heatmap (no horizontal scroll)"],
            horizontal=True, key="hourly_view_mode", label_visibility="collapsed",
        )

        def _render_hourly_block(scope_df, scope_label, key_suffix):
            """One heading + table + download button for a given scope. Each
            supervisor gets their own self-contained block so the image can be
            shared with just that team, without other teams' numbers in it."""
            hdf = _build_hourly_df(scope_df)
            grid = build_hourly_color_grid(hdf, hour_col_labels)
            if hourly_view_mode.startswith("📋"):
                st.dataframe(style_hourly_table(hdf, hour_col_labels), use_container_width=True,
                             hide_index=True, height=dataframe_height(len(hdf)))
            else:
                render_hourly_heatmap(hdf, hour_col_labels, grid)

            n_inst = scope_df["installer_id"].nunique()
            # Same glance figures as the on-screen header, including the
            # forecast, computed for THIS scope (a supervisor's own team when
            # split) so each shared image is self-contained.
            scope_fc, _, scope_end = forecast_total_installs(
                scope_df, sorted(scope_df["installer_id"].unique()), f"{day_end_choice}:00")
            glance = (
                f"Total: {len(scope_df)}   |   Active Installers: {n_inst}   |   "
                f"Avg/Installer: {round(len(scope_df) / n_inst, 1) if n_inst else 0}   |   "
                f"Forecast by {scope_end[:5]}: {scope_fc if scope_fc is not None else 'N/A'}"
            )
            scope_line = f"{scope_label}   |   " if scope_label else ""
            title = (f"Installer-Wise Hourly Count — {sel_date}\n"
                     f"{scope_line}Last install: {str(max(scope_df['time']))[:5]}\n{glance}")
            safe_label = (scope_label or "All").replace(" ", "_").replace(":", "")
            download_image_button(
                hdf, f"Hourly_Count_{sel_date}_{safe_label}.png", key=f"dl_img_hourly_{key_suffix}",
                color_grid=grid, title=title,
            )

        if sel_supervisor == "All supervisors" and len(sups_today) > 1:
            # Combined first for the overall picture, then a separate table per
            # supervisor, each shareable as its own image.
            sub_hdr("chart", "All Teams Combined")
            _render_hourly_block(day_df, "All supervisors", "all")
            for i, sup in enumerate(day_df.groupby("supervisor").size().sort_values(ascending=False).index):
                sup_df = day_df[day_df["supervisor"] == sup]
                sub_hdr("users", f"{sup} — {len(sup_df)} installs")
                _render_hourly_block(sup_df, f"Supervisor: {sup}", f"sup{i}")
        else:
            scope_label = "" if sel_supervisor == "All supervisors" else f"Supervisor: {sel_supervisor}"
            _render_hourly_block(day_df, scope_label, "single")


        # -- Section-wise summary (combines every section's uploaded file for this date) --
        sec_hdr("pin", "Section-Wise Summary")
        if has_col(day_df, "location"):
            section_df = day_df.copy()
            section_df["location"] = section_df["location"].replace("", "Unspecified").fillna("Unspecified")
            section_summary = section_df.groupby("location").size().reset_index(name="Installs")
            section_summary.columns = ["Section", "Installs"]
            section_summary = section_summary.sort_values("Installs", ascending=False)
            render_count_cards(
                [(r["Section"], int(r["Installs"])) for _, r in section_summary.iterrows()],
                columns=3, total_label="Total",
            )
        else:
            st.info("No Section data on these records yet — re-upload with the Section column present to see this breakdown.")

        # -- Daily calendar for the month of the date being viewed -----------
        _cal_month = str(sel_date)[:7]
        sec_hdr("calendar", f"Daily Installs — {month_label(_cal_month)}")
        render_daily_calendar(_cal_month)

        # -- Half-day split --------------------------------------------------
        sec_hdr("half", "Half-Day Split")
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
        download_image_button(half_display_df, f"Half_Day_Split_{sel_date}.png", key="dl_img_half",
                              title=f"Half-Day Split — {sel_date}\n{analytics_img_meta}")

        # -- Average install time -------------------------------------------
        sec_hdr("gauge", "Active Pace / Installer")
        avg_rows = []
        for inst in installers:
            sub = day_df[day_df["installer_id"] == inst].sort_values("time")
            first_t, last_t = sub["time"].iloc[0], sub["time"].iloc[-1]
            n = len(sub)
            active_pace, _break_min, _gaps = compute_active_pace(sub["time"].tolist())
            avg_rows.append({
                "Installer": inst, "First Install": first_t, "Last Install": last_t,
                "Total Installs": n,
                # "—" rather than 0.0: a lone install has no measurable rhythm,
                # and 0.0 would read as "instant" and colour as fastest.
                "Avg Time/Install (min)": round(active_pace, 1) if active_pace is not None else "—",
            })
        avg_df = pd.DataFrame(avg_rows).sort_values("Total Installs", ascending=False)
        st.dataframe(
            _style_map(avg_df.style, avg_time_style, subset=["Avg Time/Install (min)"]),
            use_container_width=True, hide_index=True, height=dataframe_height(len(avg_df)),
        )
        download_image_button(
            avg_df, f"Avg_Install_Time_{sel_date}.png", key="dl_img_avg",
            color_grid=build_single_col_color_grid(avg_df, "Avg Time/Install (min)", avg_time_colors),
            title=f"Active Pace / Installer — {sel_date}\n{analytics_img_meta}",
        )

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
        sec_hdr("download", "Update Installs From Analytics")
        st.markdown("""
        <div class="info-box">
        Pushes this date's records into Installations. Never double-counts. Unmapped login IDs are flagged.
        </div>
        """, unsafe_allow_html=True)

        if not has_col(day_df, "location") or not has_col(day_df, "meter_type") or (day_df["location"].eq("").all() and day_df["meter_type"].eq("").all()):
            st.caption("No Location/Meter Type on these records — will push as 'Unspecified', not counted in 1PH/3PH.")

        # Triggered either from this button or the Update Installs action in the
        # tab's top bar, which sets the flag before this block runs.
        _push_now = st.button(f"Update Installs For {sel_date}", type="primary", use_container_width=True)
        if st.session_state.pop("trigger_analytics_push", False):
            _push_now = True
        if _push_now:
            push_records = []
            for _, r in day_df_all.iterrows():
                rec = {"date": r["date"], "time": r["time"], "installer_id": r["installer_id"]}
                for col in ["location", "meter_type", "sno", "old_meter_no", "new_meter_no", "lat", "long"]:
                    rec[col] = r[col] if col in day_df_all.columns else ""
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
    tab_action_bar("map")
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
        data_min_d, data_max_d = (valid_dates.min(), valid_dates.max()) if not valid_dates.empty else (today_ist(), today_ist())

        # Always today. Before the day's file is uploaded this simply shows
        # zero pins — the quick-pick buttons below jump to other ranges.
        today = today_ist()
        default_range = [today, today]

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
            # Only reachable if the picker is cleared mid-session; show nothing
            # rather than a message.
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

        if pinned.empty and total_in_range > 0:
            # Only when records exist but carry no coordinates. Previously this
            # also fired when nothing was selected at all, which is not a
            # missing-coordinates problem.
            st.warning(f"⚠️ None of the {total_in_range} record(s) in this filter have latitude/longitude on file.")
        else:
            center_lat, center_lon = pinned["_lat"].mean(), pinned["_long"].mean()
            tooltip_df = pinned.rename(columns={"_lat": "lat", "_long": "lon"}).copy()
            for col in ["sno", "old_meter_no", "new_meter_no", "tech_name", "location", "date"]:
                if col not in tooltip_df.columns:
                    tooltip_df[col] = ""
            for col in ["sno", "old_meter_no", "new_meter_no"]:
                tooltip_df[col] = tooltip_df[col].apply(clean_id_value)

            layer = pdk.Layer(
                "ScatterplotLayer",
                data=tooltip_df,
                get_position=["lon", "lat"],
                get_fill_color=[0, 180, 192, 200],
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
                    "style": {"backgroundColor": "#14181F", "color": "white", "fontSize": "12px"},
                },
            )
            st.pydeck_chart(deck, use_container_width=True)

            # -- Select a pin: see lat/long as copyable text -----------------
            sub_hdr("pin", "Select A Pin")
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
                        f'<a href="https://www.google.com/maps?q={pin_lat},{pin_lon}" target="_blank" class="wa-btn" style="background:var(--accent);">📍 Open In Maps</a>',
                        unsafe_allow_html=True,
                    )
                detail_bits = [f"**SNO:** {clean_id_value(pin_row.get('sno')) or '—'}", f"**Installer:** {pin_row.get('tech_name','—') or '—'}",
                               f"**Old Meter:** {clean_id_value(pin_row.get('old_meter_no')) or '—'}", f"**New Meter:** {clean_id_value(pin_row.get('new_meter_no')) or '—'}"]
                st.caption(" · ".join(detail_bits))

            # -- Save view + share (one click, built only when clicked) --------
            sub_hdr("download", "Export This View")
            filter_desc = f"{', '.join(map_loc_filter) if map_loc_filter and len(map_loc_filter) < len(loc_options) else 'All Sections'} · {md_start} to {md_end}"
            ec1, ec2 = st.columns(2)
            _pins_snap = pinned.copy()
            with ec1:
                lazy_download_button(
                    "📷 Save Map View As PNG",
                    lambda: build_map_export_png(_pins_snap, "Install Locations", [filter_desc]),
                    f"Map_{filter_desc.split(' · ')[0].replace(', ', '_').replace(' ', '_')}.png",
                    "image/png", "map_png_export",
                )
            with ec2:
                lazy_download_button(
                    "🗺️ Share As KML File",
                    lambda: build_kml(_pins_snap, doc_name=f"Installed Meters — {filter_desc}"),
                    "installed_meters.kml", "application/vnd.google-earth.kml+xml", "map_kml_export",
                )

            with st.expander(f"📋 View {len(pinned)} record(s) as a table"):
                map_table_cols = ["date", "time", "tech_name", "location", "sno", "old_meter_no", "new_meter_no", "lat", "long"]
                map_table_cols = [c for c in map_table_cols if c in pinned.columns]
                map_table = pinned[map_table_cols].copy()
                for _idc in ["sno", "old_meter_no", "new_meter_no"]:
                    if _idc in map_table.columns:
                        map_table[_idc] = map_table[_idc].apply(clean_id_value)
                st.dataframe(map_table, use_container_width=True, hide_index=True,
                             height=dataframe_height(len(pinned), max_px=500))

    st.divider()
    with st.expander("📤 Upload Legacy/Historical Data (Map Only — does not affect Installations)"):
        render_map_legacy_upload_widget()

    st.divider()
    sec_hdr("broom", "Map Data Maintenance")
    with st.expander("🔎 Check & Remove Duplicate Map Records"):
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
#  EXPENSES  — fixed and variable costs per calendar month, and cost per install
# ═══════════════════════════════════════════════════════════════════════════════
with tab_exp:
    tab_action_bar("exp")
    df_exp_all = load_expenses()
    df_veh = load_vehicles()
    active_regs = sorted(r for r, a in zip(df_veh["reg_no"].astype(str), df_veh["is_active"]) if r.strip() and _truthy(a))

    # -- Month --------------------------------------------------------------
    _today = today_ist()
    _months = {month_key(_today)}
    _y, _m = _today.year, _today.month
    for _ in range(11):                          # the last 12 months, always offered
        _m -= 1
        if _m == 0:
            _y, _m = _y - 1, 12
        _months.add(f"{_y:04d}-{_m:02d}")
    _months |= {str(x) for x in df_exp_all["month"].unique() if str(x).strip()}
    month_opts = sorted(_months, reverse=True)
    sel_month = st.selectbox("Month", month_opts, index=month_opts.index(month_key(_today)),
                             format_func=month_label, key="exp_month")

    n1, n3 = month_installs(df_installations_master, sel_month)
    summ = expense_summary(df_exp_all, sel_month, n1, n3)

    sec_hdr("wallet", f"Cost Per Install — {month_label(sel_month)}")
    render_stat_tiles([
        ("bolt", f"{summ['installs']:,}", "Installs", f"{n1:,} 1PH · {n3:,} 3PH", "normal"),
        ("wallet", fmt_rs(summ["fixed_per_install"], 1), "Fixed", "Rs./install", "normal"),
        ("gauge", fmt_rs(summ["variable_per_install"], 1), "Variable", "Rs./install", "normal"),
        ("target", fmt_rs(summ["total_per_install"], 1), "Total", "Rs./install", "normal"),
    ])
    render_stat_tiles([
        ("wallet", fmt_rs(summ["fixed_total"]), "Fixed", "Rs. month", "normal"),
        ("gauge", fmt_rs(summ["variable_total"]), "Variable", "Rs. month", "normal"),
        ("target", fmt_rs(summ["total_cost"]), "Total cost", "Rs. month", "normal"),
    ])
    if summ["installs"] == 0 and summ["has_entries"]:
        st.info("No installs recorded for this month yet, so there is no per-install cost to show.")

    if summ["has_entries"]:
        # -- If the monthly target is met --------------------------------
        at_target = cost_at_installs(summ["fixed_total"], summ["variable_rate"], MONTHLY_TARGET)
        sub_hdr("target", f"If The Monthly Target Of {MONTHLY_TARGET:,} Is Met")
        now_pi = summ["total_per_install"]
        drop = (now_pi - at_target["total_per_install"]) if (now_pi and at_target["total_per_install"]) else None
        render_stat_tiles([
            ("wallet", fmt_rs(at_target["fixed_per_install"], 1), "Fixed", "Rs./install", "normal"),
            ("gauge", fmt_rs(at_target["variable_per_install"], 1), "Variable", "Rs./install", "normal"),
            ("target", fmt_rs(at_target["total_per_install"], 1), "Total", "Rs./install", "normal"),
            ("chart", ("—" if drop is None else f"{'-' if drop >= 0 else '+'}{abs(drop):,.1f}"),
             "vs now", "Rs./install", "normal"),
        ])
        st.markdown(
            f'<div class="info-box">Assumes this month\'s fixed costs of Rs. {summ["fixed_total"]:,.0f} '
            f'are the full month, and each extra install adds Rs. {summ["variable_rate"]:,.0f} of variable cost. '
            f'Month cost at target: Rs. {at_target["total_cost"]:,.0f}.</div>',
            unsafe_allow_html=True)

        render_cost_slider(summ["fixed_total"], summ["variable_rate"], summ["installs"], sel_month)

    if summ["by_category"]:
        sub_hdr("chart", "By Category")
        cat_df = pd.DataFrame(summ["by_category"], columns=["Type", "Category", "Month (Rs.)"])
        cat_df["Per install (Rs.)"] = cat_df["Month (Rs.)"].apply(
            lambda v: round(v / summ["installs"], 2) if summ["installs"] else None)
        cat_df["Month (Rs.)"] = cat_df["Month (Rs.)"].round(0).astype(int)
        cat_df["Share"] = cat_df["Month (Rs.)"].apply(
            lambda v: f"{v / summ['total_cost'] * 100:.0f}%" if summ["total_cost"] else "—")
        st.dataframe(cat_df, use_container_width=True, hide_index=True, height=dataframe_height(len(cat_df)))

        veh_rows = df_exp_all[(df_exp_all["month"].astype(str) == sel_month)
                              & (df_exp_all["category"].isin(EXPENSE_VEHICLE_CATEGORIES))
                              & (df_exp_all["vehicle_reg"].astype(str).str.strip() != "")]
        if not veh_rows.empty:
            sub_hdr("truck", "By Vehicle")
            vt = veh_rows.pivot_table(index="vehicle_reg", columns="category", values="amount",
                                      aggfunc="sum", fill_value=0)
            vt = vt.reindex(columns=[c for c in EXPENSE_FIXED_CATEGORIES if c in EXPENSE_VEHICLE_CATEGORIES],
                            fill_value=0)
            vt["Total"] = vt.sum(axis=1)
            vt = vt.round(0).astype(int).sort_values("Total", ascending=False).reset_index()
            vt = vt.rename(columns={"vehicle_reg": "Vehicle"})
            st.dataframe(vt, use_container_width=True, hide_index=True, height=dataframe_height(len(vt)))

    # -- Add an expense ----------------------------------------------------
    st.divider()
    sec_hdr("plus", f"Add To {month_label(sel_month)}")
    if "exp_form_version" not in st.session_state:
        st.session_state["exp_form_version"] = 0
    ev = st.session_state["exp_form_version"]

    exp_type = st.radio("Cost type", ["Fixed", "Variable"], horizontal=True, key=f"exp_type_{ev}",
                        help="Fixed: an amount for the month. Variable: a rate per install.")
    if exp_type == "Fixed":
        ec1, ec2 = st.columns(2)
        with ec1:
            exp_cat = st.selectbox("Category", EXPENSE_FIXED_CATEGORIES, key=f"exp_cat_f_{ev}")
        exp_reg = ""
        with ec2:
            if exp_cat in EXPENSE_VEHICLE_CATEGORIES:
                exp_reg = st.selectbox("Vehicle", ["-- Select --"] + active_regs, key=f"exp_reg_{ev}")
            else:
                st.write("")
        exp_item = st.text_input("Description", key=f"exp_item_{ev}", placeholder=EXPENSE_ITEM_HINT.get(exp_cat, ""))
        ec3, ec4 = st.columns([2, 1], vertical_alignment="bottom")
        with ec3:
            exp_amt = st.number_input("Amount (Rs.)", min_value=0.0, step=100.0, value=0.0, key=f"exp_amt_{ev}")
        with ec4:
            # Keyed on the category so the default re-applies when it changes.
            exp_rec = st.checkbox("Repeats monthly", value=exp_cat in EXPENSE_RECURRING_DEFAULT,
                                  key=f"exp_rec_{ev}_{exp_cat}")
        if exp_cat in EXPENSE_VEHICLE_CATEGORIES and not active_regs:
            st.warning("⚠️ Add a vehicle under Vehicles below first.")
        if st.button("➕ Add Expense", type="primary", use_container_width=True, key="exp_add_fixed"):
            if exp_amt <= 0:
                st.error("❌ Enter an amount.")
            elif exp_cat in EXPENSE_VEHICLE_CATEGORIES and exp_reg in ("", "-- Select --"):
                st.error("❌ Pick the vehicle this cost belongs to.")
            else:
                new_row = {"expense_id": f"E{int(time.time() * 1000)}", "month": sel_month, "cost_type": "Fixed",
                           "category": exp_cat, "item": exp_item.strip(),
                           "vehicle_reg": exp_reg if exp_cat in EXPENSE_VEHICLE_CATEGORIES else "",
                           "amount": exp_amt, "rate_1ph": 0, "rate_3ph": 0, "recurring": "1" if exp_rec else "0"}
                if safe_update("Expenses", pd.concat([df_exp_all[EXPENSE_COLS], pd.DataFrame([new_row])], ignore_index=True)):
                    st.session_state["exp_form_version"] += 1
                    st.success(f"✅ Added {exp_cat}: Rs. {exp_amt:,.0f} to {month_label(sel_month)}.")
                    st.rerun()
    else:
        exp_vcat = st.selectbox("Category", EXPENSE_VARIABLE_CATEGORIES, key=f"exp_cat_v_{ev}")
        cur = df_exp_all[(df_exp_all["month"].astype(str) == sel_month) & (df_exp_all["cost_type"] == "Variable")
                         & (df_exp_all["category"] == exp_vcat)]
        vc1, vc2 = st.columns(2)
        with vc1:
            r1 = st.number_input("Rate per 1PH install (Rs.)", min_value=0.0, step=5.0,
                                 value=float(cur["rate_1ph"].iloc[0]) if not cur.empty else 0.0,
                                 key=f"exp_r1_{ev}_{exp_vcat}_{sel_month}")
        with vc2:
            r3 = st.number_input("Rate per 3PH install (Rs.)", min_value=0.0, step=5.0,
                                 value=float(cur["rate_3ph"].iloc[0]) if not cur.empty else 0.0,
                                 key=f"exp_r3_{ev}_{exp_vcat}_{sel_month}")
        if n1 or n3:
            st.markdown(f'<div class="info-box">At these rates: Rs. {r1 * n1 + r3 * n3:,.0f} for '
                        f'{month_label(sel_month)} ({n1:,} × {r1:,.0f} + {n3:,} × {r3:,.0f}).</div>',
                        unsafe_allow_html=True)
        if st.button("💾 Save Rate", type="primary", use_container_width=True, key="exp_add_var"):
            if r1 <= 0 and r3 <= 0:
                st.error("❌ Enter at least one rate.")
            else:
                # One rate per variable category per month: saving again
                # UPDATES it. Two rows would silently add the rates together.
                df_new = df_exp_all[EXPENSE_COLS].copy()
                df_new = df_new[~((df_new["month"].astype(str) == sel_month) & (df_new["cost_type"] == "Variable")
                                  & (df_new["category"] == exp_vcat))]
                df_new = pd.concat([df_new, pd.DataFrame([{
                    "expense_id": f"E{int(time.time() * 1000)}", "month": sel_month, "cost_type": "Variable",
                    "category": exp_vcat, "item": "", "vehicle_reg": "", "amount": 0,
                    "rate_1ph": r1, "rate_3ph": r3, "recurring": "1"}])], ignore_index=True)
                if safe_update("Expenses", df_new):
                    st.session_state["exp_form_version"] += 1
                    st.success(f"✅ {exp_vcat} rate saved for {month_label(sel_month)}.")
                    st.rerun()

    # -- Carry repeating costs forward --------------------------------------
    _y, _m = int(sel_month[:4]), int(sel_month[5:])
    prev_month = f"{_y - 1:04d}-12" if _m == 1 else f"{_y:04d}-{_m - 1:02d}"
    prev_rec = df_exp_all[(df_exp_all["month"].astype(str) == prev_month) & df_exp_all["recurring"].apply(_truthy)]
    if not prev_rec.empty:
        this_rows = df_exp_all[df_exp_all["month"].astype(str) == sel_month]
        have = set(zip(this_rows["cost_type"], this_rows["category"], this_rows["item"].astype(str),
                       this_rows["vehicle_reg"].astype(str)))
        have_var = set(this_rows.loc[this_rows["cost_type"] == "Variable", "category"])
        to_copy = prev_rec[[
            (r["category"] not in have_var) if r["cost_type"] == "Variable"
            else ((r["cost_type"], r["category"], str(r["item"]), str(r["vehicle_reg"])) not in have)
            for _, r in prev_rec.iterrows()]]
        if not to_copy.empty:
            if st.button(f"📋 Copy {len(to_copy)} repeating cost(s) from {month_label(prev_month)}",
                         use_container_width=True, key="exp_copy_prev"):
                copied = to_copy[EXPENSE_COLS].copy()
                copied["month"] = sel_month
                base = int(time.time() * 1000)
                copied["expense_id"] = [f"E{base + i}" for i in range(len(copied))]
                if safe_update("Expenses", pd.concat([df_exp_all[EXPENSE_COLS], copied], ignore_index=True)):
                    st.success(f"✅ Copied {len(copied)} cost(s) into {month_label(sel_month)} — adjust any that changed below.")
                    st.rerun()

    # -- This month's entries: edit / delete ---------------------------------
    sec_hdr("list", f"Expenses — {month_label(sel_month)}")
    month_rows = df_exp_all[df_exp_all["month"].astype(str) == sel_month]
    if month_rows.empty:
        st.info("No expenses added for this month yet.")
    else:
        ed = month_rows.copy()
        ed["Repeats"] = ed["recurring"].apply(_truthy)
        ed.insert(0, "Delete", False)
        ed = ed.sort_values(["cost_type", "category"])
        view = ed[["Delete", "cost_type", "category", "item", "vehicle_reg", "amount", "rate_1ph", "rate_3ph",
                   "Repeats", "expense_id"]].rename(columns={
            "cost_type": "Type", "category": "Category", "item": "Description", "vehicle_reg": "Vehicle",
            "amount": "Amount (Rs.)", "rate_1ph": "Rate 1PH", "rate_3ph": "Rate 3PH"})
        edited = st.data_editor(
            view, use_container_width=True, hide_index=True, # Keyed on the sheet's version: after a save the editor starts fresh,
            # so a leftover "Delete" tick can't shift onto a different row.
            key=f"exp_editor_{sel_month}_{_sheet_version('Expenses')}",
            disabled=["Type", "Category", "Vehicle", "expense_id"],
            column_config={"expense_id": None,
                           "Amount (Rs.)": st.column_config.NumberColumn(min_value=0.0, step=100.0, format="%.0f"),
                           "Rate 1PH": st.column_config.NumberColumn(min_value=0.0, step=5.0, format="%.2f"),
                           "Rate 3PH": st.column_config.NumberColumn(min_value=0.0, step=5.0, format="%.2f")},
            height=dataframe_height(len(view)),
        )
        n_del = int(edited["Delete"].sum())
        if st.button(f"💾 Save Changes{f' (deleting {n_del})' if n_del else ''}", type="primary",
                     use_container_width=True, key="exp_save_edits"):
            if safe_update("Expenses", apply_expense_edits(df_exp_all, edited)):
                st.success("✅ Expenses updated.")
                st.rerun()

    # -- 1PH incentive & profit sharing -------------------------------------
    st.divider()
    sec_hdr("receipt", "1PH Incentive & Profit Sharing")
    _n1ph = month_installs_1ph(sel_month)
    _cpi = summ["total_per_install"]
    if _n1ph == 0:
        st.info(f"No 1PH installs recorded for {month_label(sel_month)} yet.")
    else:
        if _cpi is None:
            st.markdown('<div class="warn-box">No expenses entered for this month, so the '
                        'expense per install is 0 and the profit figures will be overstated. '
                        'Add this month\'s costs above first.</div>', unsafe_allow_html=True)
        ic1, ic2, ic3, ic4 = st.columns(4)
        with ic1:
            _old_rate = st.number_input("Old unit rate (Rs.)", min_value=0.0, step=5.0,
                                        value=float(INCENTIVE_OLD_UNIT_RATE_1PH), key="inc_old_rate")
        with ic2:
            _ret = st.number_input("Retention %", min_value=0.0, max_value=100.0, step=1.0,
                                   value=RETENTION_PCT * 100, key="inc_retention") / 100
        with ic3:
            _gst = st.number_input("GST %", min_value=0.0, max_value=100.0, step=1.0,
                                   value=GST_PCT * 100, key="inc_gst") / 100
        with ic4:
            _split = st.number_input(f"{PARTNERS[0]}'s share %", min_value=0.0, max_value=100.0, step=5.0,
                                     value=PRIMARY_SPLIT * 100, key="inc_split",
                                     help=f"Of the {PARTNERS[0]} + {PARTNERS[1]} pool; {PARTNERS[1]} gets the rest.") / 100

        # The workbook's revenue side is 1PH only. Charging the whole month's
        # cost to 1PH keeps the month's total expense whole, which is right
        # while the work is effectively all 1PH. The pro-rata option is there
        # for when 3PH volumes start and costs should be split between them.
        _basis = st.radio(
            "Expense per install", ["Whole month's cost to 1PH", "Pro rata across all installs (1PH + 3PH)"],
            horizontal=True, key="inc_expense_basis",
            help="The workbook multiplies expense/install by 1PH installs. The first option keeps the month's total cost whole; switch to pro rata once 3PH volumes are meaningful.")
        if _basis.startswith("Whole") and _n1ph:
            _cpi = (summ["total_cost"] / _n1ph) if summ["has_entries"] else None
        st.markdown(
            f'<div class="info-box">Expense per install: <b>Rs. {fmt_rs(_cpi, 2)}</b> '
            f'x {_n1ph:,} 1PH installs = <b>Rs. {fmt_rs((_cpi or 0) * _n1ph)}</b>'
            f' (month total cost Rs. {fmt_rs(summ["total_cost"])}).</div>', unsafe_allow_html=True)

        bill = calculate_1ph_incentive_billing(_n1ph)
        ps = profit_sharing_summary(_n1ph, _cpi or 0.0, _old_rate, INCENTIVE_UNIT_RATE_1PH,
                                    INCENTIVE_FLAT_ADDON_1PH, _ret, _gst, _split)
        render_stat_tiles([
            ("bolt", f"{_n1ph:,}", "1PH", "installs", "normal"),
            ("wallet", fmt_rs(_cpi, 1), "Expense", "Rs./install", "normal"),
            ("rupee", fmt_rs(bill["total_cost"]), "Billing", "Rs.", "normal"),
            ("target", fmt_rs(ps["base_profit"] + ps["additional"]), "Profit", "Rs. pool", "normal"),
        ])

        sub_hdr("chart", "Pool")
        pool = pd.DataFrame([
            ("Old pricing base revenue", ps["old_base_revenue"]),
            (f"Total expense ({fmt_rs(_cpi, 2)} x {_n1ph:,})", ps["expense_total"]),
            ("Base profit (old pricing)", ps["base_profit"]),
            (f"Retention held ({_ret * 100:.0f}%, 90 days)", ps["retention"]),
            (f"GST on old base ({_gst * 100:.0f}%)", ps["gst_old"]),
            ("Price hike amount", ps["price_hike"]),
            ("Tiered slab incentive", ps["tier_incentive"]),
            ("Additional amount (new pricing)", ps["additional"]),
            ("GST on additional", ps["gst_additional"]),
        ], columns=["Component", "Amount (Rs.)"])
        pool["Amount (Rs.)"] = pool["Amount (Rs.)"].round(0).astype(int)
        st.dataframe(pool, use_container_width=True, hide_index=True, height=dataframe_height(len(pool)))

        sub_hdr("users", "Partner-Wise")
        pw = ps["partners"].copy()
        for c in pw.columns[1:]:
            pw[c] = pw[c].round(0).astype(int)
        total_row = {"Partner": "TOTAL", **{c: int(pw[c].sum()) for c in pw.columns[1:]}}
        pw_disp = pd.concat([pw, pd.DataFrame([total_row])], ignore_index=True)
        st.dataframe(pw_disp, use_container_width=True, hide_index=True, height=dataframe_height(len(pw_disp)))

        lazy_download_button(
            "📥 Download Excel (Incentive + Profit Sharing)",
            lambda: build_incentive_workbook(sel_month, _n1ph, _cpi or 0.0, _old_rate, _ret, _gst, _split),
            f"1Ph_Incentive_Profit_{sel_month}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "inc_xlsx")

    # -- Vehicles -----------------------------------------------------------
    st.divider()
    sec_hdr("truck", "Vehicles")
    vc1, vc2, vc3 = st.columns([1.2, 2, 1], vertical_alignment="bottom")
    with vc1:
        new_reg = st.text_input("Registration No.", key=f"veh_reg_{ev}", placeholder="AP16AB1234")
    with vc2:
        new_desc = st.text_input("Description", key=f"veh_desc_{ev}", placeholder="e.g. Bolero – Chittinagar team")
    with vc3:
        if st.button("➕ Add Vehicle", use_container_width=True, key="veh_add"):
            reg = normalize_reg_no(new_reg)
            if len(reg) < 6:
                st.error("❌ Enter a valid registration number.")
            elif reg in set(df_veh["reg_no"].astype(str).map(normalize_reg_no)):
                st.error(f"❌ {reg} is already in the list.")
            else:
                if safe_update("Vehicles", pd.concat([df_veh[VEHICLE_COLS], pd.DataFrame([{
                        "reg_no": reg, "description": new_desc.strip(), "is_active": "1"}])], ignore_index=True)):
                    st.session_state["exp_form_version"] += 1
                    st.success(f"✅ Added {reg}.")
                    st.rerun()

    if df_veh.empty or df_veh["reg_no"].astype(str).str.strip().eq("").all():
        st.info("No vehicles added yet.")
    else:
        used_regs = set(df_exp_all["vehicle_reg"].astype(str))
        vview = df_veh[VEHICLE_COLS].copy()
        vview["Active"] = vview["is_active"].apply(_truthy)
        vview.insert(0, "Delete", False)
        vview = vview[["Delete", "reg_no", "description", "Active"]].rename(
            columns={"reg_no": "Registration No.", "description": "Description"})
        vedit = st.data_editor(vview, use_container_width=True, hide_index=True, key=f"veh_editor_{_sheet_version('Vehicles')}",
                               disabled=["Registration No."], height=dataframe_height(len(vview)))
        if st.button("💾 Save Vehicle Changes", use_container_width=True, key="veh_save"):
            new_veh, blocked = apply_vehicle_edits(vedit, used_regs)
            if safe_update("Vehicles", new_veh):
                if blocked:
                    st.warning(f"⚠️ {', '.join(blocked)} has costs on record, so it was marked inactive instead of deleted.")
                st.success("✅ Vehicles updated.")
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
#  LIAISONING — installs by section code, mapped to linemen, and what's payable
# ═══════════════════════════════════════════════════════════════════════════════
with tab_liaison:
    tab_action_bar("liaison")
    _today_l = today_ist()
    _lmonths = {month_key(_today_l)}
    _ly, _lm = _today_l.year, _today_l.month
    for _ in range(11):
        _lm -= 1
        if _lm == 0:
            _ly, _lm = _ly - 1, 12
        _lmonths.add(f"{_ly:04d}-{_lm:02d}")
    l_month_opts = sorted(_lmonths, reverse=True)
    l_month = st.selectbox("Month", l_month_opts, index=l_month_opts.index(month_key(_today_l)),
                           format_func=month_label, key="liaison_month")

    lt = liaisoning_table(l_month)
    df_map_l = load_liaisoning()

    sec_hdr("rupee", f"Liaisoning — {month_label(l_month)}")
    if lt.empty:
        st.info("No installs with a Consumer No recorded for this month yet.")
    else:
        mapped = lt[lt["lineman"] != ""]
        unmapped = lt[lt["lineman"] == ""]
        worked_unmapped = unmapped[unmapped["installs"] > 0]
        render_stat_tiles([
            ("bolt", f"{int(lt['installs'].sum()):,}", "Installs", "in month", "normal"),
            ("pin", f"{int((mapped['installs'] > 0).sum()):,}", "Codes", "worked", "normal"),
            ("users", f"{mapped['lineman'].nunique():,}", "Linemen", "mapped", "normal"),
            ("rupee", f"{lt['payable'].sum():,.0f}", "Payable", "Rs.", "normal"),
        ])
        if not worked_unmapped.empty:
            st.markdown(
                f'<div class="warn-box">{len(worked_unmapped)} section code(s) with '
                f'{int(worked_unmapped["installs"].sum()):,} install(s) have no lineman yet — '
                f'they are listed below and are not counted in the payable.</div>',
                unsafe_allow_html=True)

        # -- Payable per lineman ------------------------------------------
        if not mapped.empty:
            sub_hdr("users", "Payable By Lineman")
            # Includes linemen with no installs this month — a zero is itself
            # information when you are checking who to pay.
            per_lineman = mapped.groupby("lineman").agg(
                Sections=("location", lambda x: ", ".join(sorted(set(x)))),
                Codes=("section_code", lambda x: ", ".join(sorted(set(x)))),
                Installs=("installs", "sum"), Payable=("payable", "sum")).reset_index()
            per_lineman = per_lineman.rename(columns={"lineman": "Lineman"})
            per_lineman["Installs"] = per_lineman["Installs"].astype(int)
            per_lineman["Payable"] = per_lineman["Payable"].round(0).astype(int)
            per_lineman = per_lineman.sort_values("Payable", ascending=False)
            total_row = pd.DataFrame([{"Lineman": "TOTAL", "Sections": "", "Codes": "",
                                       "Installs": int(per_lineman["Installs"].sum()),
                                       "Payable": int(per_lineman["Payable"].sum())}])
            per_lineman_disp = pd.concat([per_lineman, total_row], ignore_index=True)
            st.dataframe(per_lineman_disp, use_container_width=True, hide_index=True,
                         height=dataframe_height(len(per_lineman_disp)))
            download_image_button(
                per_lineman_disp, f"Liaisoning_{l_month}.png", key="dl_img_liaison",
                title=f"Liaisoning Payable — {month_label(l_month)}\n"
                      f"{int(mapped['installs'].sum()):,} install(s) across {mapped['section_code'].nunique()} section code(s)")

        # -- Section code detail -------------------------------------------
        sub_hdr("pin", "By Section & Section Code")
        st.markdown('<div class="info-box">Every mapped section code is listed, including ones '
                    'with no installs this month.</div>', unsafe_allow_html=True)
        detail = lt.rename(columns={"location": "Section", "section_code": "Section Code",
                                    "installs": "Installs", "lineman": "Lineman",
                                    "rate": "Rate (Rs.)", "payable": "Payable (Rs.)"})
        detail["Lineman"] = detail["Lineman"].replace("", "— not mapped —")
        detail["Installs"] = detail["Installs"].astype(int)
        detail["Payable (Rs.)"] = detail["Payable (Rs.)"].round(0).astype(int)
        st.dataframe(detail, use_container_width=True, hide_index=True,
                     height=dataframe_height(len(detail), max_px=520))
        st.download_button("📥 Download CSV", data=detail.to_csv(index=False).encode("utf-8"),
                           file_name=f"liaisoning_{l_month}.csv", mime="text/csv",
                           use_container_width=True, key="liaison_csv", on_click="ignore")

    # -- Mappings that matched nothing ---------------------------------------
    # A mapping with no installs is normal early in the month, but a section
    # name that appears NOWHERE in the install data is a spelling problem —
    # worth saying so rather than leaving a lineman silently unpaid.
    _map_all = load_liaisoning()
    if not _map_all.empty:
        _counts_all = month_section_counts(l_month)
        _data_keys = {section_key(x) for x in _counts_all["location"]} if not _counts_all.empty else set()
        _worked = {(section_key(r["location"]), r["section_code"]) for _, r in _counts_all.iterrows()} if not _counts_all.empty else set()
        rows = []
        for _, r in _map_all.iterrows():
            k = section_key(r["location"])
            if (k, r["section_code"]) in _worked:
                continue
            rows.append({"Section": r["location"], "Section Code": r["section_code"], "Lineman": r["lineman"],
                         "Why": ("Section name not found in install data — check the spelling against: "
                                 + ", ".join(sorted({x for x in _counts_all['location']})) if k not in _data_keys
                                 else "No installs in this section code this month")})
        if rows:
            unmatched = pd.DataFrame(rows)
            bad_name = unmatched["Why"].str.startswith("Section name").sum()
            with st.expander(f"⚠️ {len(unmatched)} mapping(s) matched no installs"
                             + (f" — {bad_name} with a section name that isn't in the data" if bad_name else "")):
                st.dataframe(unmatched, use_container_width=True, hide_index=True,
                             height=dataframe_height(len(unmatched), max_px=320))

    # -- Map a section code to a lineman -------------------------------------
    st.divider()
    sec_hdr("plus", "Map Section Codes To Linemen")
    if "liaison_form_version" not in st.session_state:
        st.session_state["liaison_form_version"] = 0
    lv = st.session_state["liaison_form_version"]

    seen = month_section_counts(l_month)
    known_locs = sorted(set(active_locs) | set(seen["location"]) | set(df_map_l["location"]))
    lc1, lc2 = st.columns(2)
    with lc1:
        m_loc = st.selectbox("Section", known_locs or ["Unspecified"], key=f"liaison_loc_{lv}")
    already = set(df_map_l.loc[df_map_l["location"] == m_loc, "section_code"])
    with lc2:
        # Typed, not picked from a list: codes are mapped up front, before any
        # installs exist in them.
        m_codes_raw = st.text_input("Section codes", key=f"liaison_codes_{lv}_{m_loc}",
                                    placeholder="07, 12, 26  or  07-12",
                                    help="Two digits each. Separate with commas or spaces, or give a range like 07-12.")
    m_codes = parse_section_codes(m_codes_raw)
    if m_codes:
        dupes = [c for c in m_codes if c in already]
        st.markdown(
            f'<div class="info-box">{len(m_codes)} code(s): {", ".join(m_codes)}'
            + (f' — {", ".join(dupes)} already mapped in {m_loc} and will be reassigned.' if dupes else '')
            + '</div>', unsafe_allow_html=True)
    codes_here = sorted(set(seen.loc[seen["location"] == m_loc, "section_code"]))
    unmapped_here = [c for c in codes_here if c not in already]
    if unmapped_here:
        st.markdown(
            f'<div class="warn-box">Seen in {m_loc}\'s installs but not mapped yet: '
            f'<b>{", ".join(unmapped_here)}</b></div>', unsafe_allow_html=True)
    known_linemen = sorted({x for x in df_map_l["lineman"] if x})
    lc3, lc4 = st.columns(2)
    with lc3:
        pick = st.selectbox("Lineman", ["— new —"] + known_linemen, key=f"liaison_man_pick_{lv}")
        m_lineman = st.text_input("New lineman name", key=f"liaison_man_{lv}") if pick == "— new —" else pick
    with lc4:
        _default_rate = float(df_map_l.loc[df_map_l["lineman"] == pick, "rate"].iloc[0]) if (
            pick != "— new —" and not df_map_l[df_map_l["lineman"] == pick].empty) else 0.0
        m_rate = st.number_input("Rate per install (Rs.)", min_value=0.0, step=1.0,
                                 value=_default_rate, key=f"liaison_rate_{lv}_{pick}")
    if st.button("➕ Save Mapping", type="primary", use_container_width=True, key="liaison_add"):
        if not str(m_lineman).strip():
            st.error("❌ Enter the lineman's name.")
        elif not m_codes:
            st.error("❌ Enter at least one section code, e.g. 07, 12 or 07-12.")
        elif m_rate <= 0:
            st.error("❌ Enter the rate per install.")
        else:
            df_new = df_map_l[LIAISONING_COLS].copy()
            # Re-mapping a code replaces its row rather than adding a second.
            df_new = df_new[~((df_new["location"] == m_loc) & (df_new["section_code"].isin(m_codes)))]
            df_new = pd.concat([df_new, pd.DataFrame([
                {"location": m_loc, "section_code": c, "lineman": str(m_lineman).strip(), "rate": m_rate}
                for c in m_codes])], ignore_index=True)
            if safe_update("Liaisoning", df_new):
                st.session_state["liaison_form_version"] += 1
                st.success(f"✅ {len(m_codes)} section code(s) mapped to {str(m_lineman).strip()} at Rs. {m_rate:,.0f}/install.")
                st.rerun()

    # -- Existing mappings ----------------------------------------------------
    sec_hdr("list", "Current Mappings")
    if df_map_l.empty or df_map_l["section_code"].eq("").all():
        st.info("No section codes mapped yet.")
    else:
        mv = df_map_l[LIAISONING_COLS].copy()
        mv.insert(0, "Delete", False)
        mv = mv.rename(columns={"location": "Section", "section_code": "Section Code",
                                "lineman": "Lineman", "rate": "Rate (Rs.)"}).sort_values(["Section", "Section Code"])
        med = st.data_editor(
            mv, use_container_width=True, hide_index=True,
            key=f"liaison_editor_{_sheet_version('Liaisoning')}",
            disabled=["Section", "Section Code"],
            column_config={"Rate (Rs.)": st.column_config.NumberColumn(min_value=0.0, step=1.0, format="%.2f")},
            height=dataframe_height(len(mv)))
        n_del_l = int(med["Delete"].sum())
        if st.button(f"💾 Save Changes{f' (deleting {n_del_l})' if n_del_l else ''}", type="primary",
                     use_container_width=True, key="liaison_save"):
            keep = med[~med["Delete"]]
            out = pd.DataFrame({
                "location": keep["Section"],
                "section_code": keep["Section Code"].apply(normalize_section_code),
                "lineman": keep["Lineman"].astype(str).str.strip(),
                "rate": pd.to_numeric(keep["Rate (Rs.)"], errors="coerce").fillna(0.0),
            }, columns=LIAISONING_COLS)
            if safe_update("Liaisoning", out):
                st.success("✅ Mappings updated.")
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
#  INSTALLS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_inst:
    tab_action_bar("inst")
    # ── Bulk Upload from MDM Excel export ────────────────────────────────────
    sec_hdr("upload", "Bulk Upload From Excel")
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
    render_meter_search("inst")

    with st.expander("📤 Upload Legacy/Historical Data"):
        render_legacy_upload_widget(key_prefix="installs")

    st.divider()
    sec_hdr("plus", "Daily Entry")

    if not active_techs or not active_locs:
        st.warning("⚠️ Please add active Technicians and Locations in the **Admin** tab first.")
    else:
        if "installs_batch" not in st.session_state:
            st.session_state["installs_batch"] = []
        if "qm_version" not in st.session_state:
            st.session_state["qm_version"] = 0
        v = st.session_state["qm_version"]

        # ── Quick Add: same day, same location, multiple technicians ────────
        sub_hdr("bolt", "Quick Add — Same Day &amp; Location, Multiple Technicians")
        qc1, qc2 = st.columns(2)
        with qc1:
            qm_date = st.date_input("Date", value=None, key="qm_date")
        with qc2:
            qm_loc = st.selectbox("Location", ["-- Select --"] + active_locs, key="qm_loc")

        qm_techs = st.multiselect("Technicians who worked today", active_techs, key=f"qm_techs_{v}")

        qty_map = {}
        if qm_techs:
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
        sub_hdr("receipt", "Batch Ready To Save")
        batch = st.session_state["installs_batch"]
        if not batch:
            st.info("No entries yet — add some above.")
        else:
            for i, entry in enumerate(batch):
                card_col, del_col = st.columns([5, 1])
                with card_col:
                    st.markdown(f"""
                    <div class="item-card">
                        <b>{entry['tech_name']}</b> — {entry['location']}<br/>
                        <span style="color:var(--ink-600);font-size:.85rem;">
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

    sec_hdr("list", "Installation Log")
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
    tab_action_bar("inv")
    sec_hdr("download", "Inward Store Material")
    with st.form("inv_form", clear_on_submit=True):
        iv1, iv2 = st.columns(2)
        with iv1:
            idate = st.date_input("Received Date", today_ist())
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

    sec_hdr("chart", "Live Stock Summary")
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

    sec_hdr("list", "Inventory Log")
    if df_inv_t.empty:
        st.info("No inventory entries yet.")
    else:
        inv_sorted = df_inv_t.iloc[::-1].reset_index(drop=True)
        inv_exp = inv_sorted.rename(columns={"date": "Date", "type": "Type", "qty": "Qty", "mrn": "MRN No", "make": "Make"})
        st.download_button("⬇ Export Inventory CSV", inv_exp.to_csv(index=False).encode(), "inventory.csv", "text/csv", use_container_width=True, on_click="ignore")

        ITEMS_INV = 10
        total_inv_p = max(1, math.ceil(len(inv_sorted) / ITEMS_INV))
        inv_page = st.number_input(f"Page (1–{total_inv_p})", min_value=1, max_value=total_inv_p, step=1, value=1, key="inv_page")
        si, ei = (inv_page - 1) * ITEMS_INV, inv_page * ITEMS_INV
        st.dataframe(inv_sorted.iloc[si:ei], use_container_width=True, hide_index=True)

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
    tab_action_bar("admin")
    # App version lives here rather than in the header: it is only needed to
    # confirm which build is live after a deploy.
    st.markdown(f'<div class="info-box">App version <b>v{APP_VERSION}</b></div>', unsafe_allow_html=True)
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

    st.markdown("""
    <div class="warn-box" style="background:var(--surface-000);border-color:var(--hairline);color:var(--ink-600);">
    💡 <b>Tip:</b> Add one or several at once below, review them as cards, then Save Batch.
    Existing entries are listed further down as cards — tap ✏️ Edit to change details or toggle
    Active/Inactive, or 🗑️ to delete.
    </div>
    """, unsafe_allow_html=True)

    # ── Monthly install target ────────────────────────────────────────────────
    sec_hdr("target", "Monthly Install Target")
    tg1, tg2 = st.columns([2, 1])
    with tg1:
        new_target = st.number_input("Installs target for this month", min_value=0, step=100,
                                     value=int(MONTHLY_TARGET), key="monthly_target_input")
    with tg2:
        st.write("")
        if st.button("Save Target", type="primary", use_container_width=True, key="save_monthly_target"):
            if save_setting("monthly_install_target", int(new_target)):
                st.success(f"Monthly target set to {int(new_target):,}.")
                st.rerun()

    st.divider()

    subtab_tech, subtab_sup, subtab_loc = st.tabs(["👷 Technicians", "🧑‍💼 Supervisors", "📍 Locations"])

    # ── Technicians ───────────────────────────────────────────────────────────
    with subtab_tech:
        if "tech_batch" not in st.session_state:
            st.session_state["tech_batch"] = []
        if "tech_form_version" not in st.session_state:
            st.session_state["tech_form_version"] = 0
        tv = st.session_state["tech_form_version"]

        sub_hdr("plus", "Add Technicians (one or several)")
        tc1, tc2, tc3, tc4 = st.columns([2, 1, 1, 1.3])
        with tc1:
            new_t_name = st.text_input("Technician Name", key=f"new_t_name_{tv}")
        with tc2:
            new_t_phone = st.text_input("Phone (optional)", key=f"new_t_phone_{tv}")
        with tc3:
            new_t_aadhar = st.text_input("Aadhar (optional)", key=f"new_t_aadhar_{tv}")
        with tc4:
            new_t_login = st.text_input("Login ID (optional)", key=f"new_t_login_{tv}", placeholder="TL_Vinod")
        # Pick an existing supervisor to avoid typo-created duplicate groups,
        # or type a new one.
        sup_names_avail = sorted(sup_name_to_id.keys())
        sup_choice = st.selectbox("Reports to supervisor (optional)", ["— none —"] + sup_names_avail, key=f"new_t_sup_{tv}",
                                  help="Create supervisors in the Supervisors tab.")
        # Store the stable id, not the name, so renaming a supervisor later
        # doesn't orphan this technician.
        new_t_sup = sup_name_to_id.get(sup_choice, "") if sup_choice != "— none —" else ""

        if st.button("➕ Add To Batch", key="add_tech_batch_btn", type="primary", use_container_width=True):
            if not new_t_name.strip():
                st.error("❌ Technician Name is required.")
            elif any(b["name"] == new_t_name.strip() for b in st.session_state["tech_batch"]):
                st.error("❌ Already added to this batch.")
            else:
                st.session_state["tech_batch"].append({
                    "name": new_t_name.strip(), "phone": new_t_phone.strip(),
                    "aadhar": new_t_aadhar.strip(), "login_id": new_t_login.strip(),
                    "supervisor": new_t_sup,
                })
                st.session_state["tech_form_version"] += 1
                st.rerun()

        if st.session_state["tech_batch"]:
            sub_hdr("receipt", "Batch Ready To Save")
            for i, b in enumerate(st.session_state["tech_batch"]):
                bcard, bdel = st.columns([5, 1])
                with bcard:
                    detail = " · ".join([x for x in [b["phone"], b["aadhar"], b.get("login_id", ""), (f"Sup: {b.get('supervisor','')}" if b.get("supervisor") else "")] if x]) or "no details given"
                    st.markdown(f"""
                    <div class="item-card">
                        <b>{b['name']}</b><br/><span style="color:var(--ink-600);font-size:.85rem;">{detail}</span>
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
                        new_rows.append({"name": b["name"], "phone": b["phone"], "aadhar": b["aadhar"], "is_active": "1", "login_id": b.get("login_id", ""), "supervisor": b.get("supervisor", "")})
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

        sec_hdr("users", "Existing Technicians")
        df_t = df_technicians_master.copy()
        if not df_t.empty:
            df_t = df_t.rename(columns={c: str(c).strip().lower() for c in df_t.columns})
            for col in ["name", "phone", "aadhar", "is_active", "login_id", "supervisor"]:
                if col not in df_t.columns:
                    df_t[col] = ""

        if df_t.empty:
            st.info("No technicians added yet.")
        else:
            for idx, row in df_t.iterrows():
                is_active = str(row.get("is_active", "1")).strip() in ["1", "1.0", "true", "yes"]
                pill_color = "var(--brand-700)" if is_active else "var(--ink-600)"
                pill_bg = "var(--brand-050)" if is_active else "var(--surface-200)"
                pill_text = "Active" if is_active else "Inactive"

                rc1, rc2 = st.columns([5, 2])
                with rc1:
                    detail = " · ".join([x for x in [
                        str(row.get("phone", "")), str(row.get("aadhar", "")),
                        (f"Login: {row.get('login_id','')}" if str(row.get("login_id","")).strip() else ""),
                        f"Sup: {resolve_supervisor_name(row.get('supervisor','')) or '—'}",
                    ] if x]) or "no details on file"
                    st.markdown(f"""
                    <div class="item-card">
                        <b>{row.get('name','')}</b>
                        <span style="background:{pill_bg};color:{pill_color};border-radius:20px;padding:2px 10px;
                            font-size:.72rem;font-weight:700;margin-left:8px;">{pill_text}</span><br/>
                        <span style="color:var(--ink-600);font-size:.85rem;">{detail}</span>
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
                        _cur_sup_name = resolve_supervisor_name(row.get("supervisor", ""))
                        _sup_opts = ["— none —"] + sorted(sup_name_to_id.keys())
                        _sup_idx = _sup_opts.index(_cur_sup_name) if _cur_sup_name in _sup_opts else 0
                        e_sup_name = st.selectbox("Reports to supervisor", _sup_opts, index=_sup_idx)
                        e_sup = sup_name_to_id.get(e_sup_name, "") if e_sup_name != "— none —" else ""
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
                            df_t.loc[idx, ["name", "phone", "aadhar", "login_id", "supervisor", "is_active"]] = [
                                e_name.strip(), e_phone.strip(), e_aadhar.strip(), e_login.strip(), e_sup.strip(), "1" if e_active == "Active" else "0"
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

    # ── Supervisors ───────────────────────────────────────────────────────────
    with subtab_sup:

        df_sup = df_supervisors_master.copy()
        if df_sup.empty:
            df_sup = pd.DataFrame(columns=["supervisor_id", "name", "phone", "is_active"])
        for col in ["supervisor_id", "name", "phone", "is_active"]:
            if col not in df_sup.columns:
                df_sup[col] = ""

        # -- Add a supervisor --
        sub_hdr("plus", "Add Supervisor")
        if "sup_form_version" not in st.session_state:
            st.session_state["sup_form_version"] = 0
        sv_v = st.session_state["sup_form_version"]
        sc1, sc2 = st.columns([2, 1])
        with sc1:
            new_sup_name = st.text_input("Supervisor Name", key=f"new_sup_name_{sv_v}")
        with sc2:
            new_sup_phone = st.text_input("Phone (optional)", key=f"new_sup_phone_{sv_v}")
        if st.button("➕ Add Supervisor", type="primary", use_container_width=True, key="add_sup_btn"):
            nm = new_sup_name.strip()
            if not nm:
                st.error("❌ Supervisor Name is required.")
            elif nm in set(df_sup["name"].astype(str).str.strip()):
                st.error(f"❌ '{nm}' already exists.")
            else:
                new_id = f"S{int(time.time())}"  # stable id, never reused
                updated_sup = pd.concat([df_sup, pd.DataFrame([{
                    "supervisor_id": new_id, "name": nm, "phone": new_sup_phone.strip(), "is_active": "1",
                }])], ignore_index=True)
                if safe_update("Supervisors", updated_sup):
                    st.session_state["sup_form_version"] += 1
                    st.success(f"✅ Added {nm}.")
                    st.rerun()

        # -- Existing supervisors + team assignment --
        sec_hdr("users", "Supervisors &amp; Their Teams")
        df_t_all = df_technicians_master.copy()
        if not df_t_all.empty:
            df_t_all = df_t_all.rename(columns={x: str(x).strip().lower() for x in df_t_all.columns})
        for col in ["name", "login_id", "supervisor", "is_active"]:
            if col not in df_t_all.columns:
                df_t_all[col] = ""

        if df_sup.empty or df_sup["name"].astype(str).str.strip().eq("").all():
            st.info("No supervisors yet — add one above.")
        else:
            all_tech_names = sorted([n for n in df_t_all["name"].astype(str).str.strip() if n])
            for s_idx, s_row in df_sup.iterrows():
                s_id = str(s_row.get("supervisor_id", "")).strip()
                s_name = str(s_row.get("name", "")).strip()
                if not s_name:
                    continue

                # Technicians currently pointing at this supervisor (by id, or
                # legacy by name).
                assigned_mask = df_t_all["supervisor"].astype(str).str.strip().isin([s_id, s_name])
                assigned = sorted([n for n in df_t_all.loc[assigned_mask, "name"].astype(str).str.strip() if n])

                with st.expander(f"🧑‍💼 {s_name} — {len(assigned)} technician(s)"):
                    picked = st.multiselect(
                        "Assigned technicians", all_tech_names, default=assigned,
                        key=f"sup_assign_{s_id or s_idx}",
                        help="Add or remove technicians here. Removing one leaves them unassigned, it does not delete them.",
                    )
                    ac1, ac2 = st.columns(2)
                    with ac1:
                        if st.button("💾 Save Team", type="primary", use_container_width=True, key=f"save_team_{s_id or s_idx}"):
                            df_new = df_t_all.copy()
                            # Clear anyone previously under this supervisor, then
                            # set the current picks — handles unassignment too.
                            df_new.loc[df_new["supervisor"].astype(str).str.strip().isin([s_id, s_name]), "supervisor"] = ""
                            df_new.loc[df_new["name"].astype(str).str.strip().isin(picked), "supervisor"] = s_id
                            if safe_update("Technicians", df_new):
                                st.success(f"✅ {s_name}'s team updated ({len(picked)} technician(s)).")
                                st.rerun()
                    with ac2:
                        if st.button("🗑️ Delete Supervisor", use_container_width=True, key=f"del_sup_{s_id or s_idx}"):
                            st.session_state["deleting_sup"] = s_id or str(s_idx)

                    if st.session_state.get("deleting_sup") == (s_id or str(s_idx)):
                        st.markdown(f'<div class="warn-box">⚠️ Delete <b>{s_name}</b>? Their {len(assigned)} technician(s) stay, but become unassigned.</div>', unsafe_allow_html=True)
                        dy, dn = st.columns(2)
                        with dy:
                            if st.button("✅ Yes, Delete", key=f"conf_del_sup_{s_id or s_idx}"):
                                df_t_clear = df_t_all.copy()
                                df_t_clear.loc[df_t_clear["supervisor"].astype(str).str.strip().isin([s_id, s_name]), "supervisor"] = ""
                                df_sup_new = df_sup.drop(index=s_idx).reset_index(drop=True)
                                if safe_update("Supervisors", df_sup_new) and safe_update("Technicians", df_t_clear):
                                    del st.session_state["deleting_sup"]
                                    st.success(f"Deleted {s_name}.")
                                    st.rerun()
                        with dn:
                            if st.button("❌ Cancel", key=f"cancel_del_sup_{s_id or s_idx}"):
                                del st.session_state["deleting_sup"]
                                st.rerun()

            # Anyone not under any supervisor — surfaced so nobody is forgotten.
            known_ids_names = set(df_sup["supervisor_id"].astype(str).str.strip()) | set(df_sup["name"].astype(str).str.strip())
            unassigned_mask = ~df_t_all["supervisor"].astype(str).str.strip().isin(known_ids_names - {""})
            unassigned_names = sorted([n for n in df_t_all.loc[unassigned_mask, "name"].astype(str).str.strip() if n])
            if unassigned_names:
                st.markdown(f'<div class="warn-box">⚠️ Not assigned to any supervisor: <b>{", ".join(unassigned_names)}</b></div>', unsafe_allow_html=True)

    # ── Locations ─────────────────────────────────────────────────────────────
    with subtab_loc:
        if "loc_batch" not in st.session_state:
            st.session_state["loc_batch"] = []
        if "loc_form_version" not in st.session_state:
            st.session_state["loc_form_version"] = 0
        lv = st.session_state["loc_form_version"]

        sub_hdr("plus", "Add Locations (one or several)")
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
            sub_hdr("receipt", "Batch Ready To Save")
            for i, l in enumerate(st.session_state["loc_batch"]):
                bcard, bdel = st.columns([5, 1])
                with bcard:
                    st.markdown(f"""
                    <div class="item-card">
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

        sec_hdr("pin", "Existing Locations")
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
                    <div class="item-card">
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
    sec_hdr("broom", "Data Maintenance")

    with st.expander("🔢 Fix 1PH / 3PH Install Counts", expanded=not bool(get_setting("phase_fix_applied", ""))):
        already = str(get_setting("phase_fix_applied", "")).strip()
        if already:
            st.success(f"Already applied on {already}. Counts from new uploads are correct.")
        else:
            st.markdown("""
            <div class="warn-box">
            Installs whose meter type contains both a 1 and a 3 (e.g. <b>3PH 10-60A</b>)
            were counted as 1PH <b>and</b> 3PH, so Dashboard totals ran higher than Analytics.
            New uploads are now correct. This corrects what is already saved.
            </div>
            """, unsafe_allow_html=True)
            if st.button("Preview Correction", use_container_width=True, key="preview_phase_fix"):
                st.session_state["phase_fix_plan"] = plan_phase_count_repair()

            if "phase_fix_plan" in st.session_state:
                plan, values = st.session_state["phase_fix_plan"]
                if not values.empty:
                    st.markdown("**How each meter type in your data was counted:**")
                    st.dataframe(values, use_container_width=True, hide_index=True,
                                 height=dataframe_height(len(values)))
                if plan.empty:
                    st.info("No correction needed — nothing was double counted.")
                else:
                    d1, d3 = int(plan["d_1ph"].sum()), int(plan["d_3ph"].sum())
                    render_stat_tiles([
                        ("bolt", f"{d1:+,}", "1PH", "change", "danger" if d1 < 0 else "normal"),
                        ("bolt", f"{d3:+,}", "3PH", "change", "danger" if d3 < 0 else "normal"),
                        ("target", f"{d1 + d3:+,}", "Total", "change", "danger" if d1 + d3 < 0 else "normal"),
                    ])
                    by_date = plan.groupby("date")[["d_1ph", "d_3ph"]].sum().reset_index()
                    by_date["Total change"] = by_date["d_1ph"] + by_date["d_3ph"]
                    by_date.columns = ["Date", "1PH change", "3PH change", "Total change"]
                    st.dataframe(by_date.sort_values("Date", ascending=False), use_container_width=True,
                                 hide_index=True, height=dataframe_height(len(by_date)))
                    if st.button(f"Apply Correction to {len(plan)} row(s)", type="primary",
                                 use_container_width=True, key="apply_phase_fix"):
                        n = apply_phase_count_repair(plan)
                        if n:
                            # Guard: the correction is a one-time delta. Running
                            # it twice would subtract the overcount twice.
                            save_setting("phase_fix_applied", today_ist().isoformat())
                            del st.session_state["phase_fix_plan"]
                            st.success(f"✅ Corrected {n} row(s). Dashboard now matches Analytics.")
                            st.rerun()
                        else:
                            st.error("Nothing was updated — no matching Installations rows found.")

    with st.expander("🗺️ Sync Map From Installs Log"):
        st.markdown("""
        <div class="info-box">
        Copies every install in the Installs log onto the Map, and fills in
        coordinates on Map pins that are missing them. Use once to recover
        installs recorded before the Map sync covered them. Safe to re-run —
        nothing is duplicated and no install counts change.
        </div>
        """, unsafe_allow_html=True)
        if st.button("Sync Map Now", type="primary", use_container_width=True, key="sync_map_from_log"):
            df_log_all = get_data("UploadedInstallLog")
            if df_log_all.empty or "key" not in df_log_all.columns:
                st.warning("The Installs log is empty — nothing to sync.")
            else:
                recs = []
                for _, r in df_log_all.iterrows():
                    if not is_valid_installer_id(r.get("installer_id")):
                        continue
                    recs.append({col: r.get(col, "") for col in
                                 ["key", "date", "time", "installer_id", "tech_name", "location",
                                  "sno", "old_meter_no", "new_meter_no", "lat", "long"]})
                with st.spinner(f"Syncing {len(recs):,} install(s) to the Map..."):
                    changed, ok = mirror_records_to_map(recs)
                if not ok:
                    st.error("❌ Couldn't write to the Map. Check the 'MapRecords' tab exists in the Google Sheet.")
                elif changed:
                    st.success(f"✅ Added or updated {changed:,} record(s) on the Map.")
                else:
                    st.info("The Map already matches the Installs log.")
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
        Finds Installations rows whose total is <b>higher</b> than the uploaded installs behind
        them. Each flagged row holds real uploaded installs <b>plus</b> an extra amount — so the
        fix is to remove the extra, never to delete the row.
        </div>
        """, unsafe_allow_html=True)
        if st.button("🔎 Run Discrepancy Check", use_container_width=True, key="run_discrepancy_check"):
            # Kept in session state: a button drawn inside another button's
            # result never fires, because clicking it reruns the app and the
            # outer button is no longer "pressed".
            st.session_state["discrepancy_report"] = diagnose_installations_discrepancy()

        if "discrepancy_report" in st.session_state:
            flagged = st.session_state["discrepancy_report"]
            if flagged.empty:
                st.success("✅ No discrepancies — every row matches its uploaded installs.")
            else:
                extra_total = int(flagged["Implied Manual Qty"].sum())
                st.warning(f"⚠️ {len(flagged)} row(s) have {extra_total} install(s) more than their uploads support.")
                st.markdown("""
                <div class="warn-box">
                Tick a row to remove its extra — its uploaded installs stay, split correctly into
                1PH / 3PH. Leave a row unticked only if the extra is real work that was never uploaded.
                </div>
                """, unsafe_allow_html=True)
                select_all = st.checkbox("Select all rows", key="discrepancy_select_all")
                editable = flagged.copy()
                editable.insert(0, "Remove extra", bool(select_all))
                edited = st.data_editor(
                    editable, use_container_width=True, hide_index=True,
                    # The key includes the select-all state so toggling it
                    # rebuilds the ticks instead of keeping stale ones.
                    key=f"discrepancy_editor_{int(select_all)}",
                    disabled=[col for col in editable.columns if col != "Remove extra"],
                    height=dataframe_height(len(editable)),
                )
                picked = edited[edited["Remove extra"]]
                extra = int(picked["Implied Manual Qty"].sum()) if not picked.empty else 0
                if st.button(f"Remove {extra} extra install(s) from {len(picked)} row(s)", type="primary",
                             use_container_width=True, disabled=picked.empty, key="apply_discrepancy_fix"):
                    keys = list(zip(picked["Date"], picked["Technician"], picked["Location"]))
                    n = reduce_rows_to_upload_counts(keys)
                    del st.session_state["discrepancy_report"]
                    if n:
                        st.success(f"✅ Removed {extra} extra install(s) from {n} row(s). Dashboard now matches Analytics.")
                    else:
                        st.error("Nothing changed — those rows may have been edited since the check ran. Run the check again.")
                    st.rerun()

            if not flagged.empty:
                st.download_button("📥 Download This Report", data=flagged.to_csv(index=False).encode("utf-8"),
                                   file_name="installations_discrepancy_report.csv", mime="text/csv",
                                   use_container_width=True, on_click="ignore")

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
        if scanned and sno_dups.empty:
            st.success("✅ No same-SNO-same-date duplicates found in Installs data.")
        elif scanned:
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
            sub_hdr("clock", "Lower-Confidence: Same Installer, Times Within 2 Minutes")
            st.dataframe(near_dups, use_container_width=True, hide_index=True, height=dataframe_height(len(near_dups)))
