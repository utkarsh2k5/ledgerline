import numpy as np
import pytest

from app.funding.curve import bootstrap
from app.funding.liabilities import effective_duration, funding_position, present_value, pv01, stress_test
from app.funding.simulation import SimParams, simulate_funding_ratio


def test_flat_par_curve_gives_flat_zero_curve():
    curve = bootstrap([1, 10, 30], [0.04, 0.04, 0.04], max_year=30)
    assert np.allclose(curve.zero_rates, 0.04, atol=1e-12)


def test_par_bond_prices_at_par():
    tenors, pars = [1, 2, 5, 10, 30], [0.03, 0.035, 0.04, 0.045, 0.05]
    curve = bootstrap(tenors, pars, max_year=30)
    dfs = curve.discount_factors()
    for n, c in [(5, 0.04), (10, 0.045)]:
        price = c * dfs[:n].sum() + dfs[n - 1]
        assert price == pytest.approx(1.0, abs=1e-12)


def test_present_value_single_cashflow():
    curve = bootstrap([1, 50], [0.05, 0.05], max_year=50)
    cf = np.zeros(10)
    cf[9] = 100.0
    assert present_value(cf, curve) == pytest.approx(100 / 1.05 ** 10)
    assert effective_duration(cf, curve) == pytest.approx(10 / 1.05, rel=1e-4)
    assert pv01(cf, curve) > 0


def test_fully_hedged_scheme_is_insensitive_to_small_rate_moves():
    curve = bootstrap([1, 30], [0.045, 0.045], max_year=60)
    cf = np.full(40, 10.0)
    L = present_value(cf, curve)
    D = effective_duration(cf, curve)
    # one matching asset worth L with the liabilities' duration -> 100% hedge
    pos = funding_position(np.array([L]), np.array([D]), cf, curve)
    assert pos.hedge_ratio == pytest.approx(1.0, rel=1e-4)
    res = stress_test(np.array([L]), np.array([D]), np.array([False]), cf, curve,
                      {"tiny": {"rates_bps": -10, "equity": 0}})[0]
    assert abs(res["change_in_funding_ratio"]) < 1e-3


def test_unhedged_scheme_loses_when_rates_fall():
    curve = bootstrap([1, 30], [0.045, 0.045], max_year=60)
    cf = np.full(40, 10.0)
    res = stress_test(np.array([200.0]), np.array([0.0]), np.array([True]), cf, curve,
                      {"down": {"rates_bps": -100, "equity": 0}})[0]
    assert res["change_in_funding_ratio"] < 0


def test_simulation_is_reproducible_and_ordered():
    kwargs = dict(growth_assets=500, matching_assets=500, matching_duration=20, liabilities=1100,
                  liability_duration=16, base_yield=0.045, benefit_payments=np.full(10, 40.0))
    a = simulate_funding_ratio(**kwargs, params=SimParams(n_paths=2000))
    b = simulate_funding_ratio(**kwargs, params=SimParams(n_paths=2000))
    assert a == b
    p = a["percentiles"]
    for t in range(len(a["years"])):
        assert p["5"][t] <= p["25"][t] <= p["50"][t] <= p["75"][t] <= p["95"][t]
