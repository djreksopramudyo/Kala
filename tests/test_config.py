"""CostModel preset tests. us_equity_costs() is new this session -- the two
things that matter are that it's genuinely cheaper than the IDX defaults
(zero commission, no sell tax analog) and that it never uses tick_floor mode
(IDX's price-tier ticks are meaningless for USD-priced names)."""

from kala.config import CostModel, us_equity_costs


def test_us_equity_costs_has_zero_commission():
    c = us_equity_costs()
    assert c.buy_commission == 0.0
    assert c.sell_commission == 0.0


def test_us_equity_costs_sell_tax_is_the_tiny_sec_fee_not_idx_pph():
    c = us_equity_costs()
    idx = CostModel()
    assert 0.0 < c.sell_tax < idx.sell_tax   # far smaller than IDX's 0.10% PPh


def test_us_equity_costs_stays_in_flat_spread_mode():
    """tick_floor mode floors the spread at idx_tick_size(price), an
    IDR-tiered rule -- applying it to USD prices would be nonsense, so this
    preset must never use it."""
    assert us_equity_costs().spread_mode == "flat"


def test_us_equity_costs_round_trip_cheaper_than_idx_default():
    assert us_equity_costs().round_trip < CostModel().round_trip


def test_us_equity_costs_half_spread_is_tight_but_nonzero():
    c = us_equity_costs()
    assert 0.0 < c.half_spread < 0.002   # a real cost, but tight (liquid large-caps)
