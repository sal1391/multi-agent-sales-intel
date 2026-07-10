"""Unit tests for local_session.py and the demo-mode paths in snowflake_client.py.

Offline: no OpenAI, no Streamlit runtime, no snowpark connection. _period_bounds
is monkeypatched to fixed calendar windows so the handcrafted-data assertions
never rot with the calendar.
"""
import importlib
import sys
from datetime import date

import pandas as pd
import pytest

import snowflake_client as sc
from local_session import DEMO_CSV, LocalSession, get_local_session

PRIOR_YEAR_LABEL = "Prior Year 2025"
YTD_LABEL = "YTD 2026"


def _fixed_period_bounds():
    return {
        "prior_year": (date(2025, 1, 1), date(2025, 12, 31), PRIOR_YEAR_LABEL),
        "ytd": (date(2026, 1, 1), date(2026, 6, 30), YTD_LABEL),
    }


@pytest.fixture(autouse=True)
def _fixed_periods(monkeypatch):
    """Freeze the two comparison windows so tests never rot with the calendar."""
    monkeypatch.setattr(sc, "_period_bounds", _fixed_period_bounds)


# ---------------------------------------------------------------------------
# Guarded import
# ---------------------------------------------------------------------------

def test_import_snowflake_client_succeeds():
    # Already imported at module scope above; if the guarded import were
    # broken, collection of this test file would have failed outright.
    assert hasattr(sc, "get_snowflake_session")


def test_snowflake_client_survives_missing_snowpark(monkeypatch):
    # Simulate `snowflake.snowpark` being genuinely unimportable (as it is on
    # this machine's Python 3.14 environment / no wheels) and prove the
    # try/except ImportError guard around `from snowflake.snowpark import
    # Session` keeps the module importable, with Session set to None.
    monkeypatch.setitem(sys.modules, "snowflake.snowpark", None)
    try:
        importlib.reload(sc)
        assert sc.Session is None
    finally:
        # Restore normal module state for every other test in this file.
        importlib.reload(sc)


# ---------------------------------------------------------------------------
# LocalSession against the real, committed demo CSV
# ---------------------------------------------------------------------------

def test_local_session_loads_committed_csv():
    session = LocalSession()
    df = session.sql(f"SELECT COUNT(*) AS N FROM {sc.TABLE_FQN}").to_pandas()
    assert int(df["N"].iloc[0]) == 20000


def test_get_all_company_names_filters_to_baked_research_in_demo_mode():
    # Demo mode only lists companies with a baked demo_research/<slug>.md
    # file, so every dropdown selection serves saved research instead of
    # falling through to the offline stand-in analyst. Against the
    # committed repo state that's exactly the three flagship companies,
    # in SQL ORDER BY 1 (case-sensitive) order: 'H' < 'M', and within the
    # M's, 'S' (0x53) sorts before 'a' (0x61) so "MSC" < "Maersk".
    session = LocalSession()
    names = sc.get_all_company_names(session)
    assert names == ["Hapag-Lloyd", "MSC", "Maersk"]


def test_get_all_company_names_falls_back_to_full_list_when_no_baked_research(monkeypatch, tmp_path):
    from agents import researcher
    monkeypatch.setattr(researcher, "DEMO_RESEARCH_DIR", str(tmp_path))
    session = LocalSession()
    names = sc.get_all_company_names(session)
    assert names, "expected a non-empty fallback company list"
    assert names == sorted(names)
    assert "Maersk" in names
    assert "MSC" in names
    assert 25 <= len(names) <= 40


def test_get_all_company_names_filters_to_only_the_baked_files_present(monkeypatch, tmp_path):
    from agents import researcher
    (tmp_path / "maersk.md").write_text("baked", encoding="utf-8")
    monkeypatch.setattr(researcher, "DEMO_RESEARCH_DIR", str(tmp_path))
    session = LocalSession()
    names = sc.get_all_company_names(session)
    assert names == ["Maersk"]


def test_get_top5_ports_bounded_and_sorted_on_real_data():
    session = LocalSession()
    result = sc.get_top5_ports(session, "Maersk")
    for period_key in ("prior_year", "ytd"):
        rows = result[period_key]
        assert isinstance(rows, list)
        assert len(rows) <= 5
        volumes = [r["VOLUME"] for r in rows]
        assert volumes == sorted(volumes, reverse=True)


def test_get_local_session_singleton():
    first = get_local_session()
    second = get_local_session()
    assert first is second
    # Sanity: it's an actual LocalSession wired to the demo CSV.
    assert isinstance(first, LocalSession)
    assert DEMO_CSV.endswith("sales_actuals.csv")


# ---------------------------------------------------------------------------
# Handcrafted tiny dataset — exact numbers computed by hand
# ---------------------------------------------------------------------------
# Two customers (Acme Shipping, Bravo Marine), two ports (Singapore, Rotterdam).
# Every row is an inquiry (INQUIRY_FLAG=1), matching the real dataset's
# convention (see test_fake_data.py). One row for Acme Shipping falls outside
# both fixed windows (2024) to prove date filtering works.
_ROWS = [
    # CUSTOMER_NAME,   PORT_NAME,   DELIVERY_DATE, VOLUME_TONS, GROSS_PROFIT, WON_FLAG, INQUIRY_FLAG
    ("Acme Shipping", "Singapore", "2025-03-01", 100.0, 1000.0, 1, 1),
    ("Acme Shipping", "Singapore", "2025-06-01", 50.0, 300.0, 0, 1),
    ("Acme Shipping", "Rotterdam", "2025-09-01", 200.0, 4000.0, 1, 1),
    ("Acme Shipping", "Singapore", "2026-02-01", 80.0, 800.0, 1, 1),
    ("Acme Shipping", "Rotterdam", "2026-05-01", 20.0, 100.0, 0, 1),
    ("Bravo Marine", "Rotterdam", "2025-04-01", 500.0, 10000.0, 1, 1),
    ("Bravo Marine", "Singapore", "2026-01-15", 10.0, 50.0, 1, 1),
    ("Bravo Marine", "Rotterdam", "2025-12-31", 300.0, 3000.0, 0, 1),
    # Outside both windows -- must be excluded from every aggregate below.
    ("Acme Shipping", "Singapore", "2024-06-01", 999.0, 9999.0, 1, 1),
]

_COLUMNS = [
    "CUSTOMER_NAME", "PORT_NAME", "DELIVERY_DATE", "VOLUME_TONS",
    "GROSS_PROFIT", "WON_FLAG", "INQUIRY_FLAG",
]


@pytest.fixture
def mini_session(tmp_path):
    df = pd.DataFrame(_ROWS, columns=_COLUMNS)
    csv_path = tmp_path / "mini_sales_actuals.csv"
    df.to_csv(csv_path, index=False)
    return LocalSession(csv_path=str(csv_path))


def test_get_customer_metrics_exact_numbers(mini_session):
    metrics = sc.get_customer_metrics(mini_session, "Acme Shipping")

    py = metrics["prior_year"]
    assert py["VOLUME"] == pytest.approx(350.0)
    assert py["GP"] == pytest.approx(5300.0)
    # DEPLOY_MODE defaults to "demo" in tests, so MARGIN is recomputed from
    # the (here unchanged -- both already 2-sig-fig-clean) sanitized
    # VOLUME/GP and rounded to 2 decimals; see test_demo_mode_sanitizes_*
    # below for the sanitization behavior itself and test_round_sig_* for
    # _round_sig directly.
    assert py["MARGIN"] == pytest.approx(round(5300.0 / 350.0, 2))
    assert py["NUM_WON"] == 2
    assert py["NUM_INQUIRIES"] == 3
    assert py["NUM_LOST"] == 1

    ytd = metrics["ytd"]
    assert ytd["VOLUME"] == pytest.approx(100.0)
    assert ytd["GP"] == pytest.approx(900.0)
    assert ytd["MARGIN"] == pytest.approx(9.0)
    assert ytd["NUM_WON"] == 1
    assert ytd["NUM_INQUIRIES"] == 2
    assert ytd["NUM_LOST"] == 1


def test_get_customer_metrics_exact_numbers_second_customer(mini_session):
    metrics = sc.get_customer_metrics(mini_session, "Bravo Marine")

    py = metrics["prior_year"]
    assert py["VOLUME"] == pytest.approx(800.0)
    assert py["GP"] == pytest.approx(13000.0)
    assert py["MARGIN"] == pytest.approx(13000.0 / 800.0)
    assert py["NUM_WON"] == 1
    assert py["NUM_INQUIRIES"] == 2
    assert py["NUM_LOST"] == 1

    ytd = metrics["ytd"]
    assert ytd["VOLUME"] == pytest.approx(10.0)
    assert ytd["GP"] == pytest.approx(50.0)
    assert ytd["MARGIN"] == pytest.approx(5.0)
    assert ytd["NUM_WON"] == 1
    assert ytd["NUM_INQUIRIES"] == 1
    assert ytd["NUM_LOST"] == 0


def test_get_top5_ports_exact_numbers(mini_session):
    result = sc.get_top5_ports(mini_session, "Acme Shipping")

    py_rows = {r["PORT"]: r for r in result["prior_year"]}
    assert set(py_rows) == {"Singapore", "Rotterdam"}
    assert py_rows["Rotterdam"]["VOLUME"] == pytest.approx(200.0)
    assert py_rows["Rotterdam"]["GP"] == pytest.approx(4000.0)
    assert py_rows["Rotterdam"]["MARGIN"] == pytest.approx(20.0)
    assert py_rows["Rotterdam"]["NUM_WON"] == 1
    assert py_rows["Rotterdam"]["NUM_INQUIRIES"] == 1
    assert py_rows["Rotterdam"]["NUM_LOST"] == 0
    assert py_rows["Singapore"]["VOLUME"] == pytest.approx(150.0)
    assert py_rows["Singapore"]["GP"] == pytest.approx(1300.0)
    # Demo-mode sanitization recomputes MARGIN from the rounded VOLUME/GP
    # (both unchanged here) and rounds to 2 decimals -- see _round_sig.
    assert py_rows["Singapore"]["MARGIN"] == pytest.approx(round(1300.0 / 150.0, 2))
    assert py_rows["Singapore"]["NUM_WON"] == 1
    assert py_rows["Singapore"]["NUM_INQUIRIES"] == 2
    assert py_rows["Singapore"]["NUM_LOST"] == 1
    # Sorted by VOLUME descending: Rotterdam (200) before Singapore (150).
    assert [r["PORT"] for r in result["prior_year"]] == ["Rotterdam", "Singapore"]

    ytd_rows = {r["PORT"]: r for r in result["ytd"]}
    assert set(ytd_rows) == {"Singapore", "Rotterdam"}
    assert ytd_rows["Singapore"]["VOLUME"] == pytest.approx(80.0)
    assert ytd_rows["Rotterdam"]["VOLUME"] == pytest.approx(20.0)
    assert [r["PORT"] for r in result["ytd"]] == ["Singapore", "Rotterdam"]

    for period_rows in result.values():
        assert len(period_rows) <= 5


def test_fetch_all_snowflake_data_consolidated_shape(mini_session):
    data = sc.fetch_all_snowflake_data(mini_session, "Acme Shipping")

    assert set(data.keys()) == {"customer_metrics", "top5_ports", "periods", "field_dictionary"}

    assert set(data["customer_metrics"].keys()) == {"prior_year", "ytd"}
    assert data["customer_metrics"]["prior_year"]["VOLUME"] == pytest.approx(350.0)
    assert data["customer_metrics"]["ytd"]["VOLUME"] == pytest.approx(100.0)

    assert set(data["top5_ports"].keys()) == {"prior_year", "ytd"}

    assert data["periods"] == {"prior_year": PRIOR_YEAR_LABEL, "ytd": YTD_LABEL}

    assert data["field_dictionary"] == sc.FIELD_DICTIONARY
    assert "VOLUME" in data["field_dictionary"]
    assert "MARGIN" in data["field_dictionary"]


# ---------------------------------------------------------------------------
# _round_sig -- demo-mode display rounding (pure function, no session needed)
# ---------------------------------------------------------------------------

def test_round_sig_examples():
    assert sc._round_sig(10_673_296) == 11_000_000
    assert sc._round_sig(42_871) == 43_000
    assert sc._round_sig(5_673_601) == 5_700_000


def test_round_sig_zero_none_nan_passthrough():
    assert sc._round_sig(0) == 0
    assert sc._round_sig(None) is None
    nan_result = sc._round_sig(float("nan"))
    assert nan_result != nan_result  # only NaN is unequal to itself


# ---------------------------------------------------------------------------
# Demo-mode sanitization -- headline metrics round to clean numbers, counts
# and ordering are untouched. DEPLOY_MODE defaults to "demo" (see config.py),
# so most tests above already exercise this path implicitly; these tests
# pin the behavior explicitly and prove local/aws never sanitize.
# ---------------------------------------------------------------------------

def test_demo_mode_sanitizes_customer_metrics(mini_session, monkeypatch):
    monkeypatch.setattr(sc, "DEPLOY_MODE", "demo")
    metrics = sc.get_customer_metrics(mini_session, "Acme Shipping")

    py = metrics["prior_year"]
    assert py["VOLUME"] == sc._round_sig(350.0)
    assert py["GP"] == sc._round_sig(5300.0)
    assert py["MARGIN"] == pytest.approx(
        round(sc._round_sig(5300.0) / sc._round_sig(350.0), 2)
    )
    # Counts are real, never sanitized.
    assert py["NUM_WON"] == 2
    assert py["NUM_INQUIRIES"] == 3
    assert py["NUM_LOST"] == 1


def test_demo_mode_sanitizes_top5_ports_without_resorting(mini_session, monkeypatch):
    monkeypatch.setattr(sc, "DEPLOY_MODE", "demo")
    result = sc.get_top5_ports(mini_session, "Acme Shipping")

    # Order must stay exactly as the SQL returned it (VOLUME DESC), even
    # though the displayed VOLUME numbers are rounded afterward.
    assert [r["PORT"] for r in result["prior_year"]] == ["Rotterdam", "Singapore"]
    rotterdam = result["prior_year"][0]
    assert rotterdam["VOLUME"] == sc._round_sig(200.0)
    assert rotterdam["GP"] == sc._round_sig(4000.0)
    assert rotterdam["NUM_WON"] == 1
    assert rotterdam["NUM_INQUIRIES"] == 1
    assert rotterdam["NUM_LOST"] == 0


def test_local_mode_does_not_sanitize_customer_metrics(mini_session, monkeypatch):
    monkeypatch.setattr(sc, "DEPLOY_MODE", "local")
    metrics = sc.get_customer_metrics(mini_session, "Acme Shipping")

    py = metrics["prior_year"]
    assert py["VOLUME"] == pytest.approx(350.0)
    assert py["GP"] == pytest.approx(5300.0)
    assert py["MARGIN"] == pytest.approx(5300.0 / 350.0)
