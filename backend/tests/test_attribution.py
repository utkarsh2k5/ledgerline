"""Attribution maths: textbook values + properties that must hold for ANY portfolio."""
import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings as hsettings
from hypothesis import strategies as st

from app.analytics.attribution import brinson_fachler, carino_coefficients, multi_period_attribution


def test_brinson_fachler_textbook_example():
    # Two segments. Benchmark B = 0.5*0.10 + 0.5*0.02 = 0.06
    wp, wb = [0.7, 0.3], [0.5, 0.5]
    rp, rb = [0.12, 0.01], [0.10, 0.02]
    e = brinson_fachler(wp, wb, rp, rb)
    assert e.loc[0, "allocation"] == pytest.approx(0.2 * (0.10 - 0.06))
    assert e.loc[1, "allocation"] == pytest.approx(-0.2 * (0.02 - 0.06))
    assert e.loc[0, "selection"] == pytest.approx(0.5 * 0.02)
    assert e.loc[1, "selection"] == pytest.approx(0.5 * -0.01)
    assert e.loc[0, "interaction"] == pytest.approx(0.2 * 0.02)
    R = 0.7 * 0.12 + 0.3 * 0.01
    assert e.values.sum() == pytest.approx(R - 0.06)


def test_weights_must_sum_to_one():
    with pytest.raises(ValueError):
        brinson_fachler([0.6, 0.3], [0.5, 0.5], [0.1, 0.1], [0.1, 0.1])


def _weights(draw, n):
    raw = np.array(draw(st.lists(st.floats(0.01, 1.0), min_size=n, max_size=n)))
    return raw / raw.sum()


@st.composite
def portfolios(draw):
    n_seg = draw(st.integers(2, 6))
    n_months = draw(st.integers(1, 24))
    rows = []
    for m in range(n_months):
        wp, wb = _weights(draw, n_seg), _weights(draw, n_seg)
        rp = draw(st.lists(st.floats(-0.15, 0.15), min_size=n_seg, max_size=n_seg))
        rb = draw(st.lists(st.floats(-0.15, 0.15), min_size=n_seg, max_size=n_seg))
        for i in range(n_seg):
            rows.append({"month": m, "segment": f"S{i}", "wp": wp[i], "wb": wb[i], "rp": rp[i], "rb": rb[i]})
    return pd.DataFrame(rows)


@hsettings(max_examples=150, deadline=None)
@given(portfolios())
def test_single_period_effects_sum_to_excess(frame):
    for _, g in frame.groupby("month"):
        e = brinson_fachler(g.wp, g.wb, g.rp, g.rb)
        R, B = float(np.dot(g.wp, g.rp)), float(np.dot(g.wb, g.rb))
        assert e.values.sum() == pytest.approx(R - B, abs=1e-12)


@hsettings(max_examples=150, deadline=None)
@given(portfolios(), st.sampled_from(["carino", "grap"]))
def test_linked_effects_sum_to_compounded_excess(frame, method):
    res = multi_period_attribution(frame, method)
    assert res.segments["total"].sum() == pytest.approx(res.excess_return, abs=1e-10)


def test_naive_sum_does_not_reconcile_over_many_periods():
    """Why linking exists: with compounding, plain sums leave a residual."""
    rows = []
    for m in range(12):
        rows += [{"month": m, "segment": "A", "wp": 0.6, "wb": 0.5, "rp": 0.04, "rb": 0.03},
                 {"month": m, "segment": "B", "wp": 0.4, "wb": 0.5, "rp": 0.01, "rb": 0.01}]
    frame = pd.DataFrame(rows)
    naive = multi_period_attribution(frame, "sum")
    linked = multi_period_attribution(frame, "carino")
    assert abs(naive.segments["total"].sum() - naive.excess_return) > 1e-3
    assert linked.segments["total"].sum() == pytest.approx(linked.excess_return, abs=1e-12)


def test_carino_coefficient_limit_when_returns_equal():
    k = carino_coefficients(np.array([0.02, 0.02]), np.array([0.02, 0.02]))
    assert np.all(np.isfinite(k))
