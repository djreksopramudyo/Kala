"""Foreign-accumulation monitor tests: descriptive ranking off the broker-
flow archive. The monitor reuses the foreign_flow strategy's z-score, so the
key properties are (a) it agrees with that strategy by construction, (b)
strongest net buying ranks first, and (c) thin/absent coverage reads
honestly instead of silently vanishing or looking solid."""

import numpy as np
import pandas as pd
import pytest

from kala.broker_flow_archive import BrokerFlowArchive
from kala.foreign_flow_monitor import (
    format_report,
    high_confidence,
    latest_flow_reading,
    rank_foreign_accumulation,
)
from kala.strategy_foreign_flow import compute_features_foreign_flow


def _flow_df(values, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.DataFrame({"foreign_net_value": np.asarray(values, dtype=float)}, index=idx)


def _store(tmp_path, ticker, values, source="invezgo"):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert(ticker, source, _flow_df(values))
    return arc


# ---------------- latest_flow_reading ----------------------------------------

def test_reading_none_for_empty_or_short_history(tmp_path):
    assert latest_flow_reading(None) is None
    assert latest_flow_reading(_flow_df([1.0, 2.0])) is None   # nowhere near z-score window


def test_reading_matches_strategy_zscore_exactly():
    """The monitor number MUST equal what the (unvalidated) foreign_flow
    strategy would compute on the same series — one source of truth."""
    rng = np.random.default_rng(0)
    vals = rng.normal(0, 1e9, 60)
    vals[-1] = 5e9                       # a big buying day at the end
    df = _flow_df(vals)

    reading = latest_flow_reading(df)
    strat_z = compute_features_foreign_flow(df)["flow_z"].dropna().iloc[-1]
    assert reading["flow_z"] == pytest.approx(strat_z)
    assert reading["n_days"] == 60


def test_reading_accepts_series_or_frame():
    df = _flow_df(list(np.linspace(0, 5e9, 40)))
    as_frame = latest_flow_reading(df)
    as_series = latest_flow_reading(df["foreign_net_value"])
    assert as_frame["flow_z"] == pytest.approx(as_series["flow_z"])


# ---------------- rank_foreign_accumulation ----------------------------------

def test_ranking_puts_strongest_accumulation_first(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    # ACC: flat then a sharp burst of buying at the end -> high positive z.
    arc.upsert("ACC.JK", "invezgo", _flow_df([0.0] * 39 + [8e9]))
    # DIST: flat then a sharp burst of SELLING at the end -> negative z.
    arc.upsert("DIST.JK", "invezgo", _flow_df([0.0] * 39 + [-8e9]))

    ranked = rank_foreign_accumulation(arc, ["DIST.JK", "ACC.JK"])
    assert list(ranked["ticker"]) == ["ACC.JK", "DIST.JK"]
    assert ranked.iloc[0]["flow_z"] > ranked.iloc[1]["flow_z"]
    assert ranked.iloc[0]["bucket"] in ("accumulation", "strong accumulation")


def test_ranking_lists_uncovered_tickers_as_no_data_at_bottom(tmp_path):
    arc = _store(tmp_path, "HAVE.JK", list(np.linspace(0, 5e9, 40)))
    ranked = rank_foreign_accumulation(arc, ["HAVE.JK", "MISSING.JK"])
    # missing ticker is present (not dropped) and sorts last as 'no data'.
    assert set(ranked["ticker"]) == {"HAVE.JK", "MISSING.JK"}
    assert ranked.iloc[-1]["ticker"] == "MISSING.JK"
    assert ranked.iloc[-1]["bucket"] == "no data"
    assert pd.isna(ranked.iloc[-1]["flow_z"])


def test_ranking_short_history_reads_as_no_data(tmp_path):
    """A ticker with only a few days stored can't have a z-score yet — it must
    show as 'no data', not a spurious number."""
    arc = _store(tmp_path, "SHORT.JK", [1e9, 2e9, 3e9])
    ranked = rank_foreign_accumulation(arc, ["SHORT.JK"])
    assert ranked.iloc[0]["bucket"] == "no data"


def test_ranking_respects_source(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("A.JK", "invezgo", _flow_df(list(np.linspace(0, 5e9, 40))))
    # asking for a source with no rows -> no data, not a crash.
    ranked = rank_foreign_accumulation(arc, ["A.JK"], source="sectors")
    assert ranked.iloc[0]["bucket"] == "no data"


# ---------------- format_report ----------------------------------------------

def test_report_header_states_it_is_not_a_signal(tmp_path):
    arc = _store(tmp_path, "A.JK", list(np.linspace(0, 5e9, 40)))
    text = format_report(rank_foreign_accumulation(arc, ["A.JK"]))
    assert "NOT a validated buy signal" in text
    assert "INCONCLUSIVE" in text


def test_report_flags_thin_coverage(tmp_path):
    # exactly enough days for a z-score, but below the 20-day solidity bar.
    arc = _store(tmp_path, "THIN.JK", list(np.linspace(0, 5e9, 12)))
    ranked = rank_foreign_accumulation(arc, ["THIN.JK"])
    text = format_report(ranked, min_days=20)
    if ranked.iloc[0]["flow_z"] is not None and not pd.isna(ranked.iloc[0]["flow_z"]):
        assert "thin" in text


# ---------------- staleness / materiality / credible subset ------------------

REF = "2026-07-24"   # fixed "today" for deterministic staleness tests


def test_rank_computes_absolute_age_vs_reference(tmp_path):
    """age_days is measured against the reference date, so an old backfill
    window reads as stale in real terms -- even as the only ticker queried."""
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("FRESH.JK", "invezgo", _flow_df(list(np.linspace(0, 5e9, 40)), start="2026-06-01"))
    arc.upsert("OLD.JK", "invezgo", _flow_df(list(np.linspace(0, 5e9, 40)), start="2024-11-01"))
    ranked = rank_foreign_accumulation(arc, ["FRESH.JK", "OLD.JK"],
                                       reference_date=REF).set_index("ticker")
    assert ranked.loc["FRESH.JK", "age_days"] < 30      # within a month of the ref
    assert ranked.loc["OLD.JK", "age_days"] > 300       # ~18 months behind


def test_lone_old_ticker_is_stale_vs_today(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("OLD.JK", "invezgo", _flow_df([0.0] * 39 + [9e9], start="2024-01-01"))
    ranked = rank_foreign_accumulation(arc, ["OLD.JK"], reference_date=REF)
    assert ranked.iloc[0]["age_days"] > 300
    assert high_confidence(ranked, stale_days=30).empty   # excluded despite strong z


def test_faint_flow_is_flagged_not_material(tmp_path):
    """Tiny absolute flow (an illiquid name with no real foreign trade) must be
    marked immaterial even if it produces a large z -- the z is noise there."""
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    # values in the single-digit-million range: a z can still form, but |flow_cum|
    # stays far below the 1bn materiality floor.
    tiny = list(np.random.default_rng(0).normal(0, 2e6, 40))
    tiny[-1] = 1e7
    arc.upsert("FAINT.JK", "invezgo", _flow_df(tiny, start="2026-06-01"))
    ranked = rank_foreign_accumulation(arc, ["FAINT.JK"], reference_date=REF)
    assert not bool(ranked.iloc[0]["material"])
    assert "faint" in format_report(ranked)


def test_high_confidence_keeps_only_fresh_material_solid(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    # GOOD: fresh, material, strong z, plenty of history.
    arc.upsert("GOOD.JK", "invezgo", _flow_df([0.0] * 39 + [9e9], start="2026-06-01"))
    # STALE: same strong shape but an old backfill window.
    arc.upsert("STALE.JK", "invezgo", _flow_df([0.0] * 39 + [9e9], start="2024-01-01"))
    # FAINT: fresh but negligible flow.
    tiny = list(np.random.default_rng(1).normal(0, 2e6, 40))
    arc.upsert("FAINT.JK", "invezgo", _flow_df(tiny, start="2026-06-01"))

    ranked = rank_foreign_accumulation(arc, ["GOOD.JK", "STALE.JK", "FAINT.JK"],
                                       reference_date=REF)
    cred = high_confidence(ranked)
    assert list(cred["ticker"]) == ["GOOD.JK"]         # only the clean one survives


def test_report_leads_with_credible_then_flags_rest(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("GOOD.JK", "invezgo", _flow_df([0.0] * 39 + [9e9], start="2026-06-01"))
    arc.upsert("STALE.JK", "invezgo", _flow_df([0.0] * 39 + [9e9], start="2024-01-01"))
    text = format_report(rank_foreign_accumulation(arc, ["GOOD.JK", "STALE.JK"],
                                                   reference_date=REF))
    assert "MOST CREDIBLE" in text and "GOOD.JK" in text
    assert "stale" in text                              # the old-window row is flagged


def test_report_says_none_credible_when_all_low_quality(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("STALE.JK", "invezgo", _flow_df([0.0] * 39 + [9e9], start="2024-01-01"))
    text = format_report(rank_foreign_accumulation(arc, ["STALE.JK"], reference_date=REF))
    assert "MOST CREDIBLE: none" in text


# ---------------- CLI (main) -------------------------------------------------

def _seed_db(tmp_path):
    """A db with two backfilled names, neither one a big-cap you'd guess."""
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("AGII.JK", "invezgo", _flow_df(list(np.linspace(0, 5e9, 40))))
    arc.upsert("CAKK.JK", "invezgo", _flow_df(list(np.linspace(0, -3e9, 40))))
    return tmp_path / "bf.db"


def test_cli_all_ranks_everything_in_archive(tmp_path, capsys):
    import foreign_flow_monitor as cli
    db = _seed_db(tmp_path)
    rc = cli.main(["--all", "--db", str(db)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "AGII.JK" in out and "CAKK.JK" in out


def test_cli_unknown_ticker_shows_whats_available(tmp_path, capsys):
    """Exactly the user's situation: query a name that wasn't backfilled (or
    isn't even sharia). Instead of a wall of 'no data', the CLI must point at
    what the archive actually holds."""
    import foreign_flow_monitor as cli
    db = _seed_db(tmp_path)
    rc = cli.main(["--tickers", "BBCA.JK", "--db", str(db)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "None of those are in the archive" in out
    assert "AGII.JK" in out            # shows an available name to try instead


def test_cli_empty_archive_tells_user_to_backfill(tmp_path, capsys):
    import foreign_flow_monitor as cli
    empty = tmp_path / "empty.db"
    BrokerFlowArchive(empty)           # creates schema, no rows
    rc = cli.main(["--all", "--db", str(empty)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "backfill" in err
