"""Unit tests for the fake-data generator (no network, no xlsx needed).

All tests build the DataFrame from the embedded SEED_STATS snapshot, never
touching the real TM1 workbook, so they run identically in CI and locally.
"""
import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import generate_fake_data as gfd


def _generate_df():
    stats = gfd._normalize_stats(gfd.SEED_STATS)
    stats = dict(stats)
    stats["monthly_weights"] = gfd.extend_monthly_weights(stats)
    rng = np.random.default_rng(gfd.SEED)
    dims = gfd.build_dimensions(rng)
    df = gfd.generate_rows(stats, dims, rng)
    return gfd._apply_volume_scale(df)


@pytest.fixture(scope="module")
def df():
    return _generate_df()


@pytest.fixture(scope="module")
def storyline_frame(df):
    d = df.copy()
    dt = pd.to_datetime(d["DELIVERY_DATE"])
    d["YEAR"] = dt.dt.year
    d["MONTH"] = dt.dt.month
    return d


def test_schema_columns_exact_order(df):
    assert list(df.columns) == gfd.CSV_COLUMNS


def test_determinism_byte_identical_frames():
    first = _generate_df()
    second = _generate_df()
    assert_frame_equal(first, second)


def test_customers_are_curated_and_within_count_bounds(df):
    curated = set(gfd.CUSTOMER_NAMES)
    seen = set(df["CUSTOMER_NAME"].unique())
    assert seen <= curated
    assert 25 <= len(seen) <= 40


def test_date_span_covers_2024_2025_and_h2_2026(df):
    dt = pd.to_datetime(df["DELIVERY_DATE"])
    years = set(dt.dt.year.unique())
    assert 2024 in years
    assert 2025 in years
    h2_2026 = ((dt.dt.year == 2026) & (dt.dt.month >= 7)).sum()
    assert h2_2026 > 0


def test_lost_rows_zero_won_rows_positive(df):
    lost = df[df["WON_FLAG"] == 0]
    won = df[df["WON_FLAG"] == 1]
    assert (lost["VOLUME_TONS"] == 0).all()
    assert (lost["GROSS_PROFIT"] == 0).all()
    assert (won["VOLUME_TONS"] > 0).all()
    assert (won["GROSS_PROFIT"] > 0).all()
    assert (df["INQUIRY_FLAG"] == 1).all()


def test_per_customer_win_rate_within_bounds(df):
    win_rates = df.groupby("CUSTOMER_NAME")["WON_FLAG"].mean()
    assert win_rates.between(0.30, 0.85, inclusive="neither").all()


def test_brokers_are_all_fictional(df):
    fictional = set(gfd.BROKER_NAMES)
    for col in ("SUPPLY_BROKER", "ACCOUNT_BROKER", "CUSTOMER_BROKER"):
        assert set(df[col].unique()) <= fictional


def test_maersk_2026_win_rate_below_2025(storyline_frame):
    m = storyline_frame[storyline_frame["CUSTOMER_NAME"] == "Maersk"]
    wr_2025 = m.loc[m["YEAR"] == 2025, "WON_FLAG"].mean()
    wr_2026 = m.loc[m["YEAR"] == 2026, "WON_FLAG"].mean()
    assert wr_2026 < wr_2025


def test_hapag_lloyd_2026_margin_well_below_2025(storyline_frame):
    h = storyline_frame[storyline_frame["CUSTOMER_NAME"] == "Hapag-Lloyd"]

    def margin(sub):
        vol = sub["VOLUME_TONS"].sum()
        return sub["GROSS_PROFIT"].sum() / vol if vol else 0.0

    margin_2025 = margin(h[h["YEAR"] == 2025])
    margin_2026 = margin(h[h["YEAR"] == 2026])
    assert margin_2026 < margin_2025 * 0.85


def test_cma_cgm_singapore_share_rises_in_2026(storyline_frame):
    c = storyline_frame[storyline_frame["CUSTOMER_NAME"] == "CMA CGM"]

    def singapore_share(sub):
        total = sub["VOLUME_TONS"].sum()
        singapore = sub.loc[sub["PORT_NAME"] == "Singapore", "VOLUME_TONS"].sum()
        return singapore / total if total else 0.0

    share_2025 = singapore_share(c[c["YEAR"] == 2025])
    share_2026 = singapore_share(c[c["YEAR"] == 2026])
    assert share_2026 > share_2025


def test_validate_passes_on_generated_frame(df):
    # Exercises validate() end-to-end, including all five planted storylines
    # and the broker/date/column/win-rate invariants in one shot.
    gfd.validate(df)


def test_volume_scale_lands_top_customer_in_the_millions(storyline_frame):
    # Sanity-check the post-hoc VOLUME_SCALE multiply (see
    # _apply_volume_scale): Maersk's largest annual VOLUME_TONS aggregate
    # should read in the low tens of millions of tons for the "Sanitized
    # Data" demo presentation, not the hundreds of thousands raw generation
    # produces before scaling.
    m = storyline_frame[storyline_frame["CUSTOMER_NAME"] == "Maersk"]
    vol_2025 = m.loc[m["YEAR"] == 2025, "VOLUME_TONS"].sum()
    assert 5_000_000 < vol_2025 < 20_000_000


def test_apply_volume_scale_only_multiplies_volume_not_gp():
    stats = gfd._normalize_stats(gfd.SEED_STATS)
    stats = dict(stats)
    stats["monthly_weights"] = gfd.extend_monthly_weights(stats)
    rng = np.random.default_rng(gfd.SEED)
    dims = gfd.build_dimensions(rng)
    raw = gfd.generate_rows(stats, dims, rng)
    scaled = gfd._apply_volume_scale(raw)

    pd.testing.assert_series_equal(scaled["GROSS_PROFIT"], raw["GROSS_PROFIT"])
    won = raw["WON_FLAG"] == 1
    expected = (raw.loc[won, "VOLUME_TONS"] * gfd.VOLUME_SCALE).round(2)
    assert (scaled.loc[won, "VOLUME_TONS"] == expected).all()
    # Lost rows are already 0 tons, so scaling is a no-op for them.
    assert (scaled.loc[~won, "VOLUME_TONS"] == 0).all()
