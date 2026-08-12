"""A missing broker-flow archive must not read as a strategy result.

sqlite creates a database file on connect, so pointing the runner at a path
that does not exist produced a valid, EMPTY archive. That merged onto 0
tickers, generated 0 trades, and printed
"VERDICT: INCONCLUSIVE — too few OOS trades to judge the edge" — a data outage
presented as a finding about the edge. Three separate layers hid the cause:
the archive created itself, attach_foreign_flow swallowed every exception, and
the verdict printed anyway.
"""

import numpy as np
import pandas as pd

from kala.broker_flow_archive import BrokerFlowArchive
from kala.strategy_foreign_flow import FLOW_COLUMN, attach_foreign_flow


def _ohlcv(idx):
    return pd.DataFrame({"Open": 1000.0, "High": 1010.0, "Low": 990.0,
                         "Close": 1000.0, "Volume": 1e6}, index=idx)


def test_archive_reports_that_it_created_itself(tmp_path):
    a = BrokerFlowArchive(str(tmp_path / "nope.db"))
    assert a.created_empty is True
    assert a.row_count() == 0


def test_existing_archive_is_not_flagged_as_created(tmp_path):
    p = tmp_path / "bf.db"
    BrokerFlowArchive(str(p))                    # create it once
    again = BrokerFlowArchive(str(p))            # now it exists
    assert again.created_empty is False


def test_row_count_tracks_content(tmp_path):
    a = BrokerFlowArchive(str(tmp_path / "bf.db"))
    idx = pd.bdate_range("2025-01-01", periods=5)
    a.upsert("AAA.JK", "invezgo",
             pd.DataFrame({"foreign_net_value": np.full(5, 1e9)}, index=idx))
    assert a.row_count() == 5


def test_broken_archive_is_logged_not_silently_empty(monkeypatch):
    """A read() that raises must leave a trace — it used to be
    indistinguishable from 'this ticker simply has no rows'.

    log_swallowed writes to results/kala.log through a non-propagating
    file handler, so neither capsys nor caplog sees it; spy on the call.
    """
    import sqlite3

    import kala.strategy_foreign_flow as sff

    seen = []
    monkeypatch.setattr(sff, "log_swallowed", lambda ctx, exc: seen.append((ctx, exc)))

    class Exploding:
        def read(self, ticker, source=None, **kw):
            raise sqlite3.OperationalError("no such column: foreign_top_broker_share")

    idx = pd.bdate_range("2025-01-01", periods=10)
    out = sff.attach_foreign_flow({"AAA.JK": _ohlcv(idx)}, Exploding())

    assert FLOW_COLUMN not in out["AAA.JK"].columns          # still non-fatal
    assert seen, "a broken archive vanished without a trace"
    ctx, exc = seen[0]
    assert "AAA.JK" in ctx
    assert isinstance(exc, sqlite3.OperationalError)


def test_empty_archive_merges_nothing(tmp_path):
    """Pins the observed symptom so the runner's guard has something to catch."""
    a = BrokerFlowArchive(str(tmp_path / "empty.db"))
    idx = pd.bdate_range("2025-01-01", periods=10)
    out = attach_foreign_flow({"AAA.JK": _ohlcv(idx), "BBB.JK": _ohlcv(idx)}, a)
    assert sum(1 for d in out.values() if FLOW_COLUMN in d.columns) == 0


def test_populated_archive_merges(tmp_path):
    a = BrokerFlowArchive(str(tmp_path / "bf.db"))
    idx = pd.bdate_range("2025-01-01", periods=30)
    a.upsert("AAA.JK", "invezgo",
             pd.DataFrame({"foreign_net_value": np.full(30, 1e9)}, index=idx))
    out = attach_foreign_flow({"AAA.JK": _ohlcv(idx)}, a)
    assert FLOW_COLUMN in out["AAA.JK"].columns
    assert out["AAA.JK"][FLOW_COLUMN].notna().sum() == 30
