import math

import numpy as np
import pytest
from hypothesis import given, settings as hsettings
from hypothesis import strategies as st

from app.analytics import returns as R


def test_modified_dietz_no_flows_is_simple_return():
    assert R.modified_dietz(100.0, 110.0, 0.0) == pytest.approx(0.10)


def test_modified_dietz_mid_month_flow():
    # BMV 100, contribution 10 mid-month, EMV 121 -> gain 11 on average capital 105
    assert R.modified_dietz(100.0, 121.0, 10.0) == pytest.approx(11 / 105)


def test_modified_dietz_zero_capital_is_nan():
    assert math.isnan(float(R.modified_dietz(0.0, 0.0, 0.0)))


def test_chain_link_and_annualise():
    assert R.chain_link([0.10, -0.10]) == pytest.approx(-0.01)
    assert R.annualise(0.21, 24) == pytest.approx(0.10)
    assert R.annualise(0.05, 6) == pytest.approx(0.05)  # never annualise sub-year periods


def test_max_drawdown():
    assert R.max_drawdown([0.10, -0.20, 0.05]) == pytest.approx(-0.20)
    assert R.max_drawdown([0.01, 0.02]) == 0.0


def test_tracking_error_zero_when_identical():
    assert R.tracking_error([0.01, 0.02, -0.01], [0.01, 0.02, -0.01]) == pytest.approx(0.0)


def test_mwr_equals_twr_without_flows():
    rets = [0.01, 0.02, -0.005, 0.015] * 3
    end = 100 * np.prod(1 + np.array(rets))
    mwr = R.money_weighted_return(100.0, [0.0] * 12, end)
    assert mwr == pytest.approx(R.chain_link(rets), rel=1e-9)


@hsettings(max_examples=60, deadline=None)
@given(st.lists(st.floats(-0.2, 0.2), min_size=12, max_size=36))
def test_annualised_volatility_scales_with_sqrt_12(rets):
    vol = R.annualised_volatility(rets)
    assert vol == pytest.approx(np.std(rets, ddof=1) * math.sqrt(12))
