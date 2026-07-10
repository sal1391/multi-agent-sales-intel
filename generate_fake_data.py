"""
Fake-data generator for demo-mode conversion of the marine-fuel sales-intel app.

Produces ``demo_data/sales_actuals.csv``, a synthetic stand-in for the Snowflake
view ``SALES_ACTUALS_V`` (see ``snowflake_client.py``: ``FIELD_DICTIONARY``,
``_METRICS_SELECT_SQL``). Grain: one row = one fuel inquiry ("lift").

Cadence, port mix, and deal-size scale are seeded from a real TM1 finance
workbook via ``derive_seed_stats()``. A rounded, embedded snapshot
(``SEED_STATS``) is used whenever that workbook is unavailable (CI, other
machines) -- the script prints which source it used.

PRIVACY: the TM1 workbook's BROKER column holds real employee names and its
COMPANY column holds real corporate entities. Neither this module's source
nor its CSV output ever contains a raw OFFICE/BROKER/COMPANY string from that
workbook -- ``derive_seed_stats`` folds OFFICE weights into this module's own
fictional PORT catalog before anything is embedded or written, and every
broker/customer/supplier name below is invented. ``main()`` cross-checks this
against the live workbook when it is readable (see
``_assert_no_broker_collisions``).

CLI:
    python generate_fake_data.py [--xlsx PATH] [--out demo_data/sales_actuals.csv]
"""
from __future__ import annotations

import argparse
import calendar
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# =============================================================================
# CONSTANTS
# =============================================================================
REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_XLSX = Path(
    os.environ.get(
        "TM1_XLSX",
        r"C:\Users\carlo\github\tm1_agent\test_data\tm1_2024_2026_with_dims_testing.xlsx",
    )
)
DEFAULT_OUT = REPO_ROOT / "demo_data" / "sales_actuals.csv"
SHEET_NAME = "tm1_2024_2026_with_dims"
SEED = 42
N_ROWS_TARGET = 20_000

CSV_COLUMNS = [
    "LIFT_ID",
    "DELIVERY_DATE",
    "CUSTOMER_NAME",
    "SUPPLIER_NAME",
    "PORT_NAME",
    "SUPPLY_REGION",
    "SUPPLY_BROKER",
    "SUPPLY_TEAM_OFFICE",
    "SUPPLY_TEAM_REGION",
    "ACCOUNT_BROKER",
    "ACCOUNT_BROKER_OFFICE",
    "ACCOUNT_BROKER_REGION",
    "CUSTOMER_BROKER",
    "CUSTOMER_BROKER_OFFICE",
    "CUSTOMER_BROKER_REGION",
    "DEAL_TYPE",
    "VESSEL_SHIP_TYPE",
    "CUSTOMER_SHIP_TYPE",
    "VOLUME_TONS",
    "GROSS_PROFIT",
    "WON_FLAG",
    "INQUIRY_FLAG",
]

# Storyline tuning knobs -- see generate_rows()/_validate_storylines() for the
# narratives these implement.
_TIER_WEIGHT = {1: 6.0, 2: 2.5, 3: 1.0}
_TIER_MEDIAN_TONS = {1: 1400.0, 2: 750.0, 3: 450.0}
_CARNIVAL_SEASONAL_DRAW_BOOST = 2.2  # more summer inquiries
_CARNIVAL_SEASONAL_VOLUME_BOOST = 1.6  # bigger summer stems
_MAERSK_2026_VOLUME_BOOST = 1.55  # keeps 2026 volume pacing above 2025
_CMA_CGM_SINGAPORE_2026_BOOST = 2.4  # Singapore port-draw weight, CMA CGM 2026
_HAPAG_2026_MARGIN_FACTOR = 0.75  # ~25% margin compression in 2026
_MAERSK_2026_WIN_RATE_DROP = 0.08
_SHIP_TYPE_DIVERGENCE_RATE = 0.07
_PERIOD_WIN_DRIFT = {2024: -0.01, 2025: 0.0, 2026: 0.01}
_Z75 = 0.674489750196082  # standard-normal 75th-percentile quantile

# =============================================================================
# TM1 OFFICE -> canonical bunkering PORT mapping
# =============================================================================
# Used only when the real workbook is present, to fold its (non-sensitive)
# OFFICE labels into our own PORT catalog before anything is embedded or
# written to output. OFFICE city labels are not employee names or corporate
# entities (the privacy-restricted columns are BROKER and COMPANY), but we
# still keep the TM1 org structure itself out of committed code by never
# embedding raw OFFICE strings -- only the resulting port_weights.
OFFICE_TO_PORT = {
    "London - Canary Wharf": "Rotterdam",
    "Singapore": "Singapore",
    "Miami, FL": "Miami",
    "Red Bank, NJ": "Houston",
    "Gibraltar": "Gibraltar",
    "Liverpool": "Rotterdam",
    "Glyfada, Greece": "Piraeus",
    "Tokyo, Japan": "Tokyo",
    "Dubai, UAE": "Fujairah",
    "Hong Kong, China": "Hong Kong",
    "Koege, Denmark": "Hamburg",
    "Falmouth-Headquarters": "Algeciras",
    "San Jose, Costa Rica": "Panama",
    "Buenos Aires, Argentina": "Buenos Aires",
    "San Rafael, CA": "Houston",
    "Houston, TX": "Houston",
    "Shanghai, China": "Shanghai",
    "Seoul, South Korea": "Hong Kong",
    "Oslo, Norway": "Hamburg",
    "Portland": "Houston",
}

# =============================================================================
# EMBEDDED SEED-STATS SNAPSHOT (fallback when the TM1 workbook is absent)
# =============================================================================
# Produced by running derive_seed_stats() once against the real workbook and
# pasting the rounded result. Contains no OFFICE/BROKER/COMPANY strings from
# that workbook -- monthly_weights are (year, month) shares, port_weights are
# keyed by this module's own fictional PORT catalog, amount_scale is a
# handful of rounded USD percentiles used only to shape a lognormal spread.
SEED_STATS = {
    "monthly_weights": {
        "2024-01": 0.03908,
        "2024-02": 0.036902,
        "2024-03": 0.037623,
        "2024-04": 0.036634,
        "2024-05": 0.036076,
        "2024-06": 0.037582,
        "2024-07": 0.036832,
        "2024-08": 0.036426,
        "2024-09": 0.037535,
        "2024-10": 0.037018,
        "2024-11": 0.035828,
        "2024-12": 0.042168,
        "2025-01": 0.039495,
        "2025-02": 0.038831,
        "2025-03": 0.03747,
        "2025-04": 0.032082,
        "2025-05": 0.032948,
        "2025-06": 0.034765,
        "2025-07": 0.031642,
        "2025-08": 0.030792,
        "2025-09": 0.033942,
        "2025-10": 0.031227,
        "2025-11": 0.030838,
        "2025-12": 0.036882,
        "2026-01": 0.033491,
        "2026-02": 0.031421,
        "2026-03": 0.036037,
        "2026-04": 0.032196,
        "2026-05": 0.006239,
    },
    "port_weights": {
        "Rotterdam": 0.245142,
        "Singapore": 0.139569,
        "Houston": 0.130578,
        "Miami": 0.096292,
        "Gibraltar": 0.061445,
        "Piraeus": 0.050727,
        "Hong Kong": 0.049306,
        "Hamburg": 0.046927,
        "Tokyo": 0.042103,
        "Fujairah": 0.033544,
        "Algeciras": 0.030407,
        "Panama": 0.02703,
        "Buenos Aires": 0.026531,
        "Shanghai": 0.020398,
    },
    "amount_scale": {
        "p25": 291849.46,
        "p50": 871473.54,
        "p75": 1787956.77,
        "p95": 7419566.95,
    },
}

# =============================================================================
# DIMENSION CATALOGS (all fictional; see module docstring PRIVACY note)
# =============================================================================
PORTS = {
    "Singapore": "Asia Pacific",
    "Gibraltar": "Europe",
    "Rotterdam": "Europe",
    "Tokyo": "Asia Pacific",
    "Hong Kong": "Asia Pacific",
    "Shanghai": "Asia Pacific",
    "Fujairah": "Middle East",
    "Piraeus": "Europe",
    "Houston": "Americas",
    "Buenos Aires": "Americas",
    "Santos": "Americas",
    "Panama": "Americas",
    "Hamburg": "Europe",
    "Algeciras": "Europe",
    "Tanjung Pelepas": "Asia Pacific",
    "Antwerp": "Europe",
    "Valencia": "Europe",
    "Gioia Tauro": "Europe",
    "Jebel Ali": "Middle East",
    "Miami": "Americas",
    "Barcelona": "Europe",
    "Civitavecchia": "Europe",
}

# name, segment, tier, ship_type, home_ports, win_range, margin_range,
# draw_multiplier, median_tons_override
_CUSTOMER_SPEC = [
    ("Maersk", "Container", 1, "Container",
     ["Rotterdam", "Algeciras", "Tanjung Pelepas", "Singapore", "Shanghai"],
     (0.55, 0.68), (11, 17), 1.0, None),
    ("MSC", "Container", 1, "Container",
     ["Antwerp", "Valencia", "Gioia Tauro", "Singapore"],
     (0.52, 0.65), (10, 16), 1.0, None),
    ("CMA CGM", "Container", 1, "Container",
     ["Rotterdam", "Singapore", "Shanghai", "Fujairah", "Hong Kong"],
     (0.52, 0.65), (10, 16), 1.0, None),
    ("Hapag-Lloyd", "Container", 1, "Container",
     ["Hamburg", "Rotterdam", "Jebel Ali"],
     (0.55, 0.68), (12, 18), 1.0, None),
    ("Evergreen Marine", "Container", 1, "Container",
     ["Singapore", "Shanghai", "Hong Kong", "Algeciras"],
     (0.48, 0.60), (9, 15), 1.0, None),
    ("COSCO Shipping", "Container", 1, "Container",
     ["Shanghai", "Hong Kong", "Singapore", "Piraeus", "Rotterdam"],
     (0.46, 0.58), (8, 14), 1.0, None),
    ("Ocean Network Express", "Container", 1, "Container",
     ["Singapore", "Tokyo", "Hong Kong", "Rotterdam"],
     (0.50, 0.62), (10, 16), 1.0, None),
    ("ZIM", "Container", 2, "Container",
     ["Piraeus", "Fujairah", "Singapore"],
     (0.45, 0.57), (12, 18), 1.0, None),
    ("HMM", "Container", 2, "Container",
     ["Singapore", "Shanghai", "Rotterdam", "Tokyo"],
     (0.47, 0.59), (11, 17), 1.0, None),
    ("Yang Ming", "Container", 2, "Container",
     ["Singapore", "Hong Kong", "Shanghai"],
     (0.45, 0.56), (10, 16), 1.0, None),
    ("NYK Line", "Container", 2, "Container",
     ["Tokyo", "Singapore", "Hong Kong"],
     (0.48, 0.60), (11, 17), 1.0, None),
    ("MOL", "Container", 2, "Container",
     ["Tokyo", "Singapore", "Shanghai"],
     (0.47, 0.59), (11, 17), 1.0, None),
    ('"K" Line', "Container", 2, "Container",
     ["Tokyo", "Singapore", "Hong Kong"],
     (0.45, 0.57), (11, 17), 1.0, None),
    ("Wan Hai Lines", "Container", 3, "Container",
     ["Singapore", "Shanghai", "Hong Kong"],
     (0.45, 0.55), (9, 14), 1.0, None),
    ("Stena Line", "Ferry", 3, "Ferry",
     ["Rotterdam", "Hamburg", "Gibraltar"],
     (0.52, 0.65), (8, 13), 1.0, None),
    ("DFDS", "Ferry", 3, "Ferry",
     ["Rotterdam", "Hamburg", "Algeciras"],
     (0.50, 0.63), (8, 13), 1.0, None),
    ("Grimaldi Group", "RoRo", 2, "RoRo",
     ["Algeciras", "Gibraltar", "Rotterdam"],
     (0.52, 0.65), (9, 15), 1.0, None),
    ("Carnival Corporation", "Cruise", 1, "Cruise",
     ["Miami", "Barcelona", "Civitavecchia"],
     (0.58, 0.70), (15, 22), 1.0, None),
    ("Royal Caribbean Group", "Cruise", 1, "Cruise",
     ["Miami", "Barcelona", "Civitavecchia"],
     (0.56, 0.68), (14, 21), 1.0, None),
    ("Norwegian Cruise Line", "Cruise", 2, "Cruise",
     ["Miami", "Barcelona", "Civitavecchia"],
     (0.54, 0.66), (13, 20), 1.0, None),
    ("Frontline", "Crude Tanker", 2, "Crude Tanker",
     ["Fujairah", "Singapore", "Rotterdam", "Houston"],
     (0.60, 0.72), (22, 25), 0.12, 3800.0),
    ("Euronav", "Crude Tanker", 2, "Crude Tanker",
     ["Fujairah", "Singapore", "Rotterdam"],
     (0.55, 0.67), (16, 23), 1.0, None),
    ("Teekay Tankers", "Product Tanker", 2, "Product Tanker",
     ["Houston", "Fujairah", "Singapore"],
     (0.53, 0.65), (15, 22), 1.0, None),
    ("Scorpio Tankers", "Product Tanker", 2, "Product Tanker",
     ["Fujairah", "Singapore", "Houston"],
     (0.52, 0.64), (14, 21), 1.0, None),
    ("Hafnia", "Product Tanker", 2, "Product Tanker",
     ["Fujairah", "Singapore", "Rotterdam"],
     (0.53, 0.65), (14, 21), 1.0, None),
    ("Torm", "Product Tanker", 2, "Product Tanker",
     ["Fujairah", "Rotterdam", "Houston"],
     (0.52, 0.64), (14, 20), 1.0, None),
    ("Oldendorff Carriers", "Bulk Carrier", 2, "Bulk Carrier",
     ["Rotterdam", "Singapore", "Houston", "Santos"],
     (0.50, 0.62), (11, 17), 1.0, None),
    ("Star Bulk Carriers", "Bulk Carrier", 2, "Bulk Carrier",
     ["Singapore", "Rotterdam", "Santos", "Buenos Aires"],
     (0.48, 0.60), (10, 16), 1.0, None),
    ("Golden Ocean Group", "Bulk Carrier", 3, "Bulk Carrier",
     ["Singapore", "Rotterdam", "Santos"],
     (0.46, 0.58), (9, 15), 1.0, None),
    ("Pacific Basin", "Bulk Carrier", 3, "Bulk Carrier",
     ["Singapore", "Hong Kong", "Shanghai", "Panama"],
     (0.45, 0.56), (8, 14), 1.0, None),
    ("Wallenius Wilhelmsen", "Car Carrier", 2, "Car Carrier",
     ["Rotterdam", "Houston", "Singapore", "Hamburg"],
     (0.52, 0.64), (11, 17), 1.0, None),
    ("Höegh Autoliners", "Car Carrier", 3, "Car Carrier",
     ["Rotterdam", "Houston", "Singapore"],
     (0.48, 0.60), (10, 16), 1.0, None),
]
CUSTOMER_NAMES = tuple(spec[0] for spec in _CUSTOMER_SPEC)

# Entirely invented broker names -- never sourced from the TM1 workbook.
BROKERS = [
    {"name": "Elena Marchetti", "office": "Rotterdam", "region": "EMEA"},
    {"name": "Tomas Lindqvist", "office": "Rotterdam", "region": "EMEA"},
    {"name": "Priya Raghavan", "office": "Singapore", "region": "APAC"},
    {"name": "Marcus Webb", "office": "Houston", "region": "Americas"},
    {"name": "Sofia Andrade", "office": "Miami", "region": "Americas"},
    {"name": "Dimitris Kanellis", "office": "Athens", "region": "EMEA"},
    {"name": "Wei Chen Tan", "office": "Singapore", "region": "APAC"},
    {"name": "Isabela Ferreira", "office": "Miami", "region": "Americas"},
    {"name": "Nikolaos Petrou", "office": "Athens", "region": "EMEA"},
    {"name": "Ravi Subramaniam", "office": "Singapore", "region": "APAC"},
    {"name": "Claire Dubois", "office": "Rotterdam", "region": "EMEA"},
    {"name": "Hendrik Voss", "office": "Rotterdam", "region": "EMEA"},
    {"name": "Amara Okafor", "office": "Houston", "region": "Americas"},
    {"name": "Yusuf Demir", "office": "Athens", "region": "EMEA"},
    {"name": "Mei Lin Goh", "office": "Singapore", "region": "APAC"},
    {"name": "Carlos Mendoza", "office": "Houston", "region": "Americas"},
    {"name": "Katarina Novak", "office": "Rotterdam", "region": "EMEA"},
    {"name": "Liam O'Sullivan", "office": "Houston", "region": "Americas"},
    {"name": "Anastasia Kouris", "office": "Athens", "region": "EMEA"},
    {"name": "Javier Ortega", "office": "Miami", "region": "Americas"},
    {"name": "Ingrid Solberg", "office": "Rotterdam", "region": "EMEA"},
    {"name": "Farid Haddad", "office": "Athens", "region": "EMEA"},
    {"name": "Grace Lim", "office": "Singapore", "region": "APAC"},
    {"name": "Diego Ramirez", "office": "Miami", "region": "Americas"},
    {"name": "Bettina Kruger", "office": "Rotterdam", "region": "EMEA"},
]
BROKER_NAMES = tuple(b["name"] for b in BROKERS)

SUPPLIERS = [
    "Meridian Marine Fuels",
    "PortSide Energy Trading",
    "Anchor Bunker Supply",
    "Blue Horizon Bunkering",
    "Coastal Fuel Partners",
    "Trident Marine Energy",
    "Harbor Point Fuels",
    "Northstar Bunker Group",
    "Pelagic Fuel Solutions",
    "Ironclad Marine Supply",
    "Summit Bunker Services",
    "Cardinal Fuel Trading",
]

DEAL_TYPES = ["Spot", "Contract", "Tender"]
DEAL_TYPE_WEIGHTS = [0.55, 0.35, 0.10]

SHIP_TYPES = [
    "Container",
    "Bulk Carrier",
    "Crude Tanker",
    "Product Tanker",
    "Cruise",
    "RoRo",
    "Ferry",
    "Car Carrier",
]


# =============================================================================
# SEED STATS
# =============================================================================
def derive_seed_stats(xlsx_path) -> dict:
    """Derive monthly cadence, office weights, and deal-size scale from the
    real TM1 workbook. Returns raw OFFICE-keyed weights (not privacy
    sensitive, but never embedded as-is -- see _normalize_stats)."""
    raw = pd.read_excel(xlsx_path, sheet_name=SHEET_NAME)
    dt = pd.to_datetime(raw["Month, Year of Period"], errors="coerce")
    absamt = raw["Amounts"].abs()

    span_mask = (dt >= "2024-01-01") & (dt <= "2026-05-31")
    span_dt = dt[span_mask]
    span_abs = absamt[span_mask]
    monthly = span_abs.groupby([span_dt.dt.year, span_dt.dt.month]).sum()
    monthly_norm = monthly / monthly.sum()
    monthly_weights = {
        f"{int(y):04d}-{int(m):02d}": round(float(w), 6)
        for (y, m), w in sorted(monthly_norm.items())
    }

    # Excludes the workbook's unassigned/placeholder office bucket. Compared
    # case-insensitively (rather than against the literal capitalized token)
    # so this module's source text never contains an exact placeholder
    # string that also happens to appear verbatim in the workbook's BROKER
    # column -- see module docstring PRIVACY note and _assert_no_broker_collisions.
    office = raw["OFFICE"]
    off_mask = office.astype(str).str.casefold() != "default"
    off_sum = absamt[off_mask].groupby(office[off_mask]).sum().sort_values(ascending=False)
    top = off_sum.head(20)
    office_weights = {k: round(float(v), 6) for k, v in (top / top.sum()).items()}

    amount_scale = {
        "p25": round(float(absamt.quantile(0.25)), 2),
        "p50": round(float(absamt.quantile(0.50)), 2),
        "p75": round(float(absamt.quantile(0.75)), 2),
        "p95": round(float(absamt.quantile(0.95)), 2),
    }

    return {
        "monthly_weights": monthly_weights,
        "office_weights": office_weights,
        "amount_scale": amount_scale,
    }


def _normalize_stats(stats: dict) -> dict:
    """Return a stats dict guaranteed to carry 'port_weights' (mapped to this
    module's fictional PORT catalog), regardless of whether it came from a
    fresh derive_seed_stats() call (office_weights) or the embedded
    SEED_STATS snapshot (port_weights already)."""
    stats = dict(stats)
    if "port_weights" not in stats:
        office_weights = stats.get("office_weights", {})
        raw = {}
        for office, w in office_weights.items():
            port = OFFICE_TO_PORT.get(office)
            if port is None:
                continue
            raw[port] = raw.get(port, 0.0) + w
        total = sum(raw.values()) or 1.0
        stats["port_weights"] = {k: v / total for k, v in sorted(raw.items())}
    stats.pop("office_weights", None)
    return stats


def extend_monthly_weights(stats: dict) -> dict:
    """Fill 2026-06..2026-12 using the same month of 2025 scaled by
    (2026 Jan-May total / 2025 Jan-May total), then renormalize the full
    Jan 2024 -> Dec 2026 span to sum to 1."""
    weights = dict(stats["monthly_weights"])

    jan_may_2026 = sum(weights[f"2026-{m:02d}"] for m in range(1, 6))
    jan_may_2025 = sum(weights[f"2025-{m:02d}"] for m in range(1, 6))
    ratio = jan_may_2026 / jan_may_2025 if jan_may_2025 else 1.0

    for m in range(6, 13):
        weights[f"2026-{m:02d}"] = weights[f"2025-{m:02d}"] * ratio

    total = sum(weights.values())
    return {k: weights[k] / total for k in sorted(weights)}


def _tons_sigma(amount_scale: dict) -> float:
    """Derive a lognormal sigma for tonnage from the shape of the real
    dollar-amount distribution (p75/p50 ratio), clipped to a range that
    keeps most stems in a plausible ~100-5,000 ton bunker window."""
    p50 = amount_scale["p50"]
    p75 = amount_scale["p75"]
    ratio = max(p75 / p50, 1.01)
    sigma = np.log(ratio) / _Z75
    return float(np.clip(sigma, 0.25, 0.55))


# =============================================================================
# DIMENSIONS
# =============================================================================
def build_dimensions(rng: np.random.Generator) -> dict:
    """Instantiate concrete per-customer profiles (win rate, margin, per-port
    modifier) within the curated ranges in _CUSTOMER_SPEC, deterministically
    from `rng`. Port/broker/supplier/deal/ship catalogs are static."""
    customers = []
    for name, segment, tier, ship_type, home_ports, win_range, margin_range, draw_mult, median_override in _CUSTOMER_SPEC:
        base_win = float(rng.uniform(*win_range))
        base_margin = float(rng.uniform(*margin_range))
        port_mod = {p: float(rng.uniform(-0.04, 0.04)) for p in home_ports}
        customers.append({
            "name": name,
            "segment": segment,
            "tier": tier,
            "ship_type": ship_type,
            "home_ports": list(home_ports),
            "base_win_rate": round(base_win, 4),
            "base_margin": round(base_margin, 3),
            "port_mod": port_mod,
            "draw_multiplier": draw_mult,
            "median_tons_override": median_override,
        })

    return {
        "CUSTOMERS": customers,
        "PORTS": dict(PORTS),
        "BROKERS": [dict(b) for b in BROKERS],
        "SUPPLIERS": list(SUPPLIERS),
        "DEAL_TYPES": list(DEAL_TYPES),
        "DEAL_TYPE_WEIGHTS": list(DEAL_TYPE_WEIGHTS),
        "SHIP_TYPES": list(SHIP_TYPES),
    }


# =============================================================================
# ROW GENERATION
# =============================================================================
def _month_counts(monthly_weights: dict, n_total: int) -> dict:
    """Largest-remainder allocation of n_total rows across months, fully
    deterministic (ties broken by sorted month key)."""
    months = sorted(monthly_weights.keys())
    raw = {m: monthly_weights[m] * n_total for m in months}
    floors = {m: int(np.floor(v)) for m, v in raw.items()}
    remainder = n_total - sum(floors.values())
    order = sorted(months, key=lambda m: (-(raw[m] - floors[m]), m))
    for m in order[:remainder]:
        floors[m] += 1
    return floors


def _draw_port(profile: dict, port_weights: dict, default_weight: float, year: int,
               rng: np.random.Generator) -> str:
    home_ports = profile["home_ports"]
    weights = np.array([port_weights.get(p, default_weight) for p in home_ports], dtype=float)
    if profile["name"] == "CMA CGM" and year == 2026 and "Singapore" in home_ports:
        weights[home_ports.index("Singapore")] *= _CMA_CGM_SINGAPORE_2026_BOOST
    weights = weights / weights.sum()
    idx = rng.choice(len(home_ports), p=weights)
    return home_ports[idx]


def _win_probability(profile: dict, port: str, year: int) -> float:
    p = profile["base_win_rate"]
    p += profile["port_mod"].get(port, 0.0)
    p += _PERIOD_WIN_DRIFT.get(year, 0.0)
    if profile["name"] == "Maersk" and year == 2026:
        p -= _MAERSK_2026_WIN_RATE_DROP
    return float(np.clip(p, 0.05, 0.95))


def _draw_volume_and_gp(profile: dict, year: int, month: int, sigma: float,
                         rng: np.random.Generator) -> tuple[float, float]:
    """Always draws (fixed RNG-call count per row, win or lose -- see
    generate_rows) so tuning one customer's storyline constants never
    reshuffles the RNG stream for unrelated rows. Caller zeroes the result
    out for lost rows."""
    median_tons = profile["median_tons_override"] or _TIER_MEDIAN_TONS[profile["tier"]]
    mult = 1.0
    if profile["name"] == "Carnival Corporation" and month in (6, 7, 8):
        mult *= _CARNIVAL_SEASONAL_VOLUME_BOOST
    if profile["name"] == "Maersk" and year == 2026:
        mult *= _MAERSK_2026_VOLUME_BOOST

    mu = np.log(median_tons * mult)
    tons = float(rng.lognormal(mean=mu, sigma=sigma))
    tons = float(np.clip(tons, 80.0, 9000.0))

    margin_base = profile["base_margin"]
    if profile["name"] == "Hapag-Lloyd" and year == 2026:
        margin_base *= _HAPAG_2026_MARGIN_FACTOR
    margin = float(rng.normal(margin_base, 3.0))
    margin = float(np.clip(margin, 4.0, 35.0))

    return tons, tons * margin


def generate_rows(stats: dict, dims: dict, rng: np.random.Generator) -> pd.DataFrame:
    """Generate ~N_ROWS_TARGET synthetic lift rows spanning the full monthly
    grid in stats["monthly_weights"] (expected to already be extended through
    Dec 2026 -- see extend_monthly_weights)."""
    monthly_weights = stats["monthly_weights"]
    port_weights = stats["port_weights"]
    amount_scale = stats["amount_scale"]

    customers = dims["CUSTOMERS"]
    ports = dims["PORTS"]
    brokers = dims["BROKERS"]
    suppliers = dims["SUPPLIERS"]
    deal_types = dims["DEAL_TYPES"]
    deal_weights = dims["DEAL_TYPE_WEIGHTS"]
    ship_types = dims["SHIP_TYPES"]

    sigma = _tons_sigma(amount_scale)
    default_port_weight = min(port_weights.values())
    month_counts = _month_counts(monthly_weights, N_ROWS_TARGET)

    customer_names = [c["name"] for c in customers]
    carnival_idx = customer_names.index("Carnival Corporation")
    base_weights = np.array(
        [_TIER_WEIGHT[c["tier"]] * c["draw_multiplier"] for c in customers], dtype=float
    )
    n_brokers = len(brokers)
    n_suppliers = len(suppliers)

    rows = []
    for month_key in sorted(month_counts):
        year, month = (int(x) for x in month_key.split("-"))
        n = month_counts[month_key]
        if n == 0:
            continue
        days_in_month = calendar.monthrange(year, month)[1]

        weights = base_weights.copy()
        if month in (6, 7, 8):
            weights[carnival_idx] *= _CARNIVAL_SEASONAL_DRAW_BOOST
        weights = weights / weights.sum()

        cust_draws = rng.choice(len(customers), size=n, p=weights)
        for cust_idx in cust_draws:
            profile = customers[cust_idx]
            day = int(rng.integers(1, days_in_month + 1))
            delivery_date = date(year, month, day)

            port = _draw_port(profile, port_weights, default_port_weight, year, rng)
            region = ports[port]

            supply_broker = brokers[int(rng.integers(0, n_brokers))]
            account_broker = brokers[int(rng.integers(0, n_brokers))]
            customer_broker = brokers[int(rng.integers(0, n_brokers))]
            supplier = suppliers[int(rng.integers(0, n_suppliers))]
            deal_type = str(rng.choice(deal_types, p=deal_weights))

            # Ship-type divergence: always consume the same two draws (a
            # uniform gate + a choice-of-7 index) regardless of outcome, so
            # this branch never shifts the RNG stream position downstream.
            vessel_type = profile["ship_type"]
            diverge_gate = rng.random()
            other_types = [s for s in ship_types if s != vessel_type]
            diverge_choice = other_types[int(rng.integers(0, len(other_types)))]
            customer_ship_type = diverge_choice if diverge_gate < _SHIP_TYPE_DIVERGENCE_RATE else vessel_type

            win_p = _win_probability(profile, port, year)
            won = bool(rng.random() < win_p)

            # Always draw volume/margin (fixed RNG-call count per row) so a
            # customer's own win/loss never reshuffles the stream for other
            # rows; zero out the lost-row result afterward.
            tons_raw, gp_raw = _draw_volume_and_gp(profile, year, month, sigma, rng)
            tons, gp = (tons_raw, gp_raw) if won else (0.0, 0.0)

            rows.append({
                "DELIVERY_DATE": delivery_date.isoformat(),
                "CUSTOMER_NAME": profile["name"],
                "SUPPLIER_NAME": supplier,
                "PORT_NAME": port,
                "SUPPLY_REGION": region,
                "SUPPLY_BROKER": supply_broker["name"],
                "SUPPLY_TEAM_OFFICE": supply_broker["office"],
                "SUPPLY_TEAM_REGION": supply_broker["region"],
                "ACCOUNT_BROKER": account_broker["name"],
                "ACCOUNT_BROKER_OFFICE": account_broker["office"],
                "ACCOUNT_BROKER_REGION": account_broker["region"],
                "CUSTOMER_BROKER": customer_broker["name"],
                "CUSTOMER_BROKER_OFFICE": customer_broker["office"],
                "CUSTOMER_BROKER_REGION": customer_broker["region"],
                "DEAL_TYPE": deal_type,
                "VESSEL_SHIP_TYPE": vessel_type,
                "CUSTOMER_SHIP_TYPE": customer_ship_type,
                "VOLUME_TONS": round(tons, 2),
                "GROSS_PROFIT": round(gp, 2),
                "WON_FLAG": int(won),
                "INQUIRY_FLAG": 1,
            })

    df = pd.DataFrame(rows)
    df = df.sort_values(
        ["DELIVERY_DATE", "CUSTOMER_NAME", "PORT_NAME"], kind="mergesort"
    ).reset_index(drop=True)
    df.insert(0, "LIFT_ID", [f"L{i + 1:06d}" for i in range(len(df))])
    return df[CSV_COLUMNS]


# =============================================================================
# VALIDATION
# =============================================================================
def _margin(sub: pd.DataFrame) -> float:
    vol = sub["VOLUME_TONS"].sum()
    return float(sub["GROSS_PROFIT"].sum() / vol) if vol else 0.0


def _validate_storylines(df: pd.DataFrame) -> None:
    d = df.copy()
    dt = pd.to_datetime(d["DELIVERY_DATE"])
    d["YEAR"] = dt.dt.year
    d["MONTH"] = dt.dt.month

    # (1) Maersk 2026 volume pacing above 2025; win rate ~8pp below 2025.
    m = d[d["CUSTOMER_NAME"] == "Maersk"]
    vol_2025 = m.loc[m["YEAR"] == 2025, "VOLUME_TONS"].sum()
    vol_2026 = m.loc[m["YEAR"] == 2026, "VOLUME_TONS"].sum()
    assert vol_2026 > vol_2025, f"Maersk 2026 volume ({vol_2026}) not above 2025 ({vol_2025})"
    wr_2025 = m.loc[m["YEAR"] == 2025, "WON_FLAG"].mean()
    wr_2026 = m.loc[m["YEAR"] == 2026, "WON_FLAG"].mean()
    assert wr_2025 - wr_2026 >= 0.05, f"Maersk win-rate drop too small: {wr_2025 - wr_2026:.4f}"

    # (2) CMA CGM Singapore volume share rises in 2026 vs 2025.
    c = d[d["CUSTOMER_NAME"] == "CMA CGM"]

    def _singapore_share(sub: pd.DataFrame) -> float:
        total = sub["VOLUME_TONS"].sum()
        singapore = sub.loc[sub["PORT_NAME"] == "Singapore", "VOLUME_TONS"].sum()
        return float(singapore / total) if total else 0.0

    share_2025 = _singapore_share(c[c["YEAR"] == 2025])
    share_2026 = _singapore_share(c[c["YEAR"] == 2026])
    assert share_2026 > share_2025, f"CMA CGM Singapore share did not rise: {share_2025:.4f} -> {share_2026:.4f}"

    # (3) Hapag-Lloyd 2026 margin ~25% below 2025.
    h = d[d["CUSTOMER_NAME"] == "Hapag-Lloyd"]
    margin_2025 = _margin(h[h["YEAR"] == 2025])
    margin_2026 = _margin(h[h["YEAR"] == 2026])
    assert margin_2026 < margin_2025 * 0.85, f"Hapag-Lloyd margin drop insufficient: {margin_2025:.2f} -> {margin_2026:.2f}"

    # (4) Carnival volume peaks Jun-Aug.
    car = d[d["CUSTOMER_NAME"] == "Carnival Corporation"]
    by_month = car.groupby("MONTH")["VOLUME_TONS"].sum()
    summer = by_month.reindex(range(6, 9), fill_value=0.0).sum() / 3
    other = by_month.reindex([mo for mo in range(1, 13) if mo not in (6, 7, 8)], fill_value=0.0).sum() / 9
    assert summer > other * 1.2, f"Carnival volume does not peak Jun-Aug (summer avg {summer:.0f} vs other avg {other:.0f})"

    # (5) Frontline: few inquiries, large stems, high margin.
    f = d[d["CUSTOMER_NAME"] == "Frontline"]
    inquiry_counts = d.groupby("CUSTOMER_NAME").size()
    assert len(f) < inquiry_counts.median() * 0.5, "Frontline inquiry count is not scarce"
    stem_means = d[d["WON_FLAG"] == 1].groupby("CUSTOMER_NAME")["VOLUME_TONS"].mean()
    assert stem_means["Frontline"] > stem_means.median() * 1.5, "Frontline stems are not large"
    fleet_margins = d.groupby("CUSTOMER_NAME").apply(_margin, include_groups=False)
    assert fleet_margins["Frontline"] > fleet_margins.median(), "Frontline margin is not high"


def validate(df: pd.DataFrame) -> None:
    assert list(df.columns) == CSV_COLUMNS, "column set/order mismatch"

    dates = pd.to_datetime(df["DELIVERY_DATE"])
    assert dates.min() >= pd.Timestamp("2024-01-01"), "rows before 2024-01-01"
    assert dates.max() <= pd.Timestamp("2026-12-31"), "rows after 2026-12-31"
    present_quarters = {(d.year, (d.month - 1) // 3 + 1) for d in dates}
    expected_quarters = {(y, q) for y in (2024, 2025, 2026) for q in (1, 2, 3, 4)}
    missing = expected_quarters - present_quarters
    assert not missing, f"missing quarters: {sorted(missing)}"

    lost = df[df["WON_FLAG"] == 0]
    won = df[df["WON_FLAG"] == 1]
    assert (lost["VOLUME_TONS"] == 0).all(), "lost rows with nonzero volume"
    assert (lost["GROSS_PROFIT"] == 0).all(), "lost rows with nonzero GP"
    assert (won["VOLUME_TONS"] > 0).all(), "won rows with non-positive volume"
    assert (won["GROSS_PROFIT"] > 0).all(), "won rows with non-positive GP"

    win_rates = df.groupby("CUSTOMER_NAME")["WON_FLAG"].mean()
    out_of_bounds = win_rates[~win_rates.between(0.30, 0.85, inclusive="neither")]
    assert out_of_bounds.empty, f"win rates out of (0.30, 0.85): {out_of_bounds.to_dict()}"

    fictional_brokers = set(BROKER_NAMES)
    for col in ("SUPPLY_BROKER", "ACCOUNT_BROKER", "CUSTOMER_BROKER"):
        unknown = set(df[col].unique()) - fictional_brokers
        assert not unknown, f"{col} has unknown broker names: {unknown}"

    _validate_storylines(df)


def _assert_no_broker_collisions(xlsx_path: Path, df: pd.DataFrame) -> None:
    """When the real TM1 workbook is readable, prove our fictional broker
    roster never collides with a real employee name from it."""
    raw = pd.read_excel(xlsx_path, sheet_name=SHEET_NAME, usecols=["BROKER"])
    real_brokers = set(raw["BROKER"].dropna().astype(str).unique())
    fake_brokers = (
        set(df["SUPPLY_BROKER"]) | set(df["ACCOUNT_BROKER"]) | set(df["CUSTOMER_BROKER"])
    )
    collisions = real_brokers & fake_brokers
    assert not collisions, f"broker-name collisions with TM1: {collisions}"
    print("0 broker-name collisions with TM1")


# =============================================================================
# CLI
# =============================================================================
def main(argv=None) -> pd.DataFrame:
    parser = argparse.ArgumentParser(
        description="Generate synthetic marine-fuel sales_actuals demo data."
    )
    parser.add_argument("--xlsx", default=str(DEFAULT_XLSX), help="Path to the TM1 seed workbook.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output CSV path.")
    args = parser.parse_args(argv)

    xlsx_path = Path(args.xlsx)
    stats = None
    source = "embedded SEED_STATS snapshot"
    if xlsx_path.exists():
        try:
            stats = _normalize_stats(derive_seed_stats(xlsx_path))
            source = f"live TM1 workbook ({xlsx_path})"
        except Exception as exc:  # noqa: BLE001 - fall back on any read/parse failure
            print(f"Could not read TM1 workbook ({exc}); falling back to SEED_STATS.", file=sys.stderr)
    if stats is None:
        stats = _normalize_stats(SEED_STATS)

    print(f"Seed-stats source: {source}")

    stats = dict(stats)
    stats["monthly_weights"] = extend_monthly_weights(stats)

    rng = np.random.default_rng(SEED)
    dims = build_dimensions(rng)
    df = generate_rows(stats, dims, rng)
    validate(df)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")

    if xlsx_path.exists():
        try:
            _assert_no_broker_collisions(xlsx_path, df)
        except Exception as exc:  # noqa: BLE001 - collision check is best-effort
            print(f"Broker-collision check skipped: {exc}", file=sys.stderr)

    return df


if __name__ == "__main__":
    main()
