"""Universe list sanity tests. ALL_SHARIA_STOCKS (IDX) had no dedicated test
file before; US_SHARIA_STOCKS is new this session and, per its own docstring,
a hand-curated starter list (no live source was fetchable) -- so its tests
lean on structural invariants and the documented exclusion methodology
(no financials/insurers/aerospace-defense/payment-networks) rather than
asserting membership against an external source this session couldn't reach."""

from kala.universe import ALL_SHARIA_STOCKS, US_SHARIA_STOCKS

# Well-known US large-caps that the module's own docstring says must NOT be in
# US_SHARIA_STOCKS: conventional banks/insurers/asset managers, financial
# exchanges & data, payment networks (excluded alongside financials per SPUS's
# methodology), aerospace & defense, alcohol/tobacco/gambling.
_EXCLUDED_BY_METHODOLOGY = {
    "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP",   # banks / conventional finance
    "UNH", "CI", "ELV", "HUM",                      # health INSURERS specifically
    "BRK.B", "BRK-B", "AIG", "MET", "PRU",           # insurers / financial conglomerates
    "V", "MA", "PYPL", "FIS", "FISV", "GPN",         # payment networks / data processing
    "ICE", "CME", "NDAQ", "SPGI", "MCO",             # financial exchanges & data
    "RTX", "LMT", "NOC", "GD", "BA",                 # aerospace & defense
    "MO", "PM",                                      # tobacco
}


# ---------------- ALL_SHARIA_STOCKS (IDX) -- basic invariants -----------------

def test_idx_universe_nonempty():
    assert len(ALL_SHARIA_STOCKS) > 0


def test_idx_universe_no_duplicates():
    assert len(ALL_SHARIA_STOCKS) == len(set(ALL_SHARIA_STOCKS))


def test_idx_universe_all_have_jk_suffix():
    assert all(t.endswith(".JK") for t in ALL_SHARIA_STOCKS)


# ---------------- US_SHARIA_STOCKS -- structural + methodology -----------------

def test_us_universe_nonempty_and_reasonably_sized():
    assert 30 <= len(US_SHARIA_STOCKS) <= 200


def test_us_universe_no_duplicates():
    assert len(US_SHARIA_STOCKS) == len(set(US_SHARIA_STOCKS))


def test_us_universe_bare_tickers_no_suffix():
    """yfinance expects bare US tickers -- no '.JK' (that's the IDX suffix)
    and no exchange suffix at all."""
    assert all("." not in t and "-" not in t for t in US_SHARIA_STOCKS)


def test_us_universe_all_uppercase():
    assert all(t == t.upper() for t in US_SHARIA_STOCKS)


def test_us_universe_disjoint_from_idx_universe():
    """Sanity check the two lists weren't accidentally merged/confused."""
    assert not (set(US_SHARIA_STOCKS) & set(ALL_SHARIA_STOCKS))


def test_us_universe_excludes_conventional_financials_and_excluded_sectors():
    """The module's own docstring states financials/insurers/payment-networks/
    financial-exchanges/aerospace-defense/tobacco are deliberately excluded --
    this pins that promise so a future edit can't silently reintroduce one."""
    present = set(US_SHARIA_STOCKS) & _EXCLUDED_BY_METHODOLOGY
    assert not present, f"methodology-excluded ticker(s) leaked into US_SHARIA_STOCKS: {present}"


def test_us_universe_includes_some_expected_mega_caps():
    """Not a compliance claim -- just proves the list wasn't left empty/typo'd:
    a few of the most obviously-compliant, uncontroversial names should be
    present (mega-cap tech with minimal debt)."""
    for t in ("AAPL", "MSFT", "NVDA"):
        assert t in US_SHARIA_STOCKS
