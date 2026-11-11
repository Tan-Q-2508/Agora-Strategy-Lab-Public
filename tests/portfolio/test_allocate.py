"""The allocator by hand (PORTFOLIO §4, D-84): screen, pick, weigh, cap, fit to the budget."""

from __future__ import annotations

import numpy as np
import pytest

from backend.portfolio import allocate as al

T = 400  # study days


def _cand(
    name: str,
    pattern: list[int],
    scale: float,
    *,
    sharpe: float = 1.0,
    dsr: float = 0.9,
    trades: int = 20,
    net: float = 5000.0,
    pf: float = 1.5,
    dearest: float = 100.0,
    size_pct: float = 19.0,
    symbols: list[str] | None = None,
) -> al.Candidate:
    reps = T // len(pattern)
    study = np.array(pattern * reps, dtype=float) * scale
    exam = np.array(pattern * 25, dtype=float) * scale
    returns = np.concatenate([study, exam])
    days = [f"d{k:04d}" for k in range(len(returns) + 1)]
    return al.Candidate(
        key=name,
        name=name,
        strategy_id=1,
        version_id=1,
        symbols=symbols or [name.upper()],
        size_pct=size_pct,
        max_open=5,
        dearest=dearest,
        days=days,
        returns=returns,
        split_index=len(study),
        exam={"trades": trades, "wins": trades // 2 + 2, "net": net, "profit_factor": pf},
        sharpe=sharpe,
        dsr=dsr,
    )


# A moves +a, −a, +a, −a; B moves +b, +b, −b, −b: uncorrelated by construction.
A = [1, -1, 1, -1]
B = [1, 1, -1, -1]
C = [1, -1, -1, 1]
OPEN = al.Risk("test", reserve=0.0, cap=1.0, most=6, target_vol=10.0)


def test_inverse_volatility_on_a_shrunk_covariance_by_hand() -> None:
    # a = 0.01, b = 0.02: sample variances 1e-4 and 4e-4, μ = 2.5e-4, covariance 0
    # d² = ((1e-4 − μ)² + (4e-4 − μ)²) / 2 = 2.25e-8; b̄² = a²b² / T = 1e-10; δ = 0.004444
    # shrunk: 1.006667e-4 and 3.993333e-4 → 1/σ = 99.6683 and 50.0417 → 0.66572, 0.33428
    a, b = _cand("a", A, 0.01), _cand("b", B, 0.02)
    w, cov, method = al.weigh([a, b], OPEN)
    assert method == "inverse volatility"
    assert cov[0, 1] == pytest.approx(0.0, abs=1e-12)
    assert w == pytest.approx([0.66572, 0.33428], abs=1e-4)


def test_stronger_evidence_gets_more() -> None:
    # same as above with scores 1 and 0.5: tilt × (1, 0.75) → (0.66572, 0.25071) → 0.72641
    a, b = _cand("a", A, 0.01, sharpe=1.0, dsr=1.0), _cand("b", B, 0.02, sharpe=0.5, dsr=1.0)
    w, _cov, _m = al.weigh([a, b], OPEN)
    assert w == pytest.approx([0.72641, 0.27359], abs=1e-4)


def test_three_or_more_use_hierarchical_risk_parity() -> None:
    cands = [_cand("a", A, 0.01), _cand("b", B, 0.01), _cand("c", C, 0.01)]
    w, _cov, method = al.weigh(cands, OPEN)
    assert method == "hierarchical risk parity"
    assert w == pytest.approx([1 / 3] * 3, abs=1e-3)  # equal, uncorrelated risks


def test_the_screen_and_its_reasons() -> None:
    ok = _cand("ok", A, 0.01)
    few = _cand("few", B, 0.01, trades=5)
    loser = _cand("loser", B, 0.01, net=-10)
    weak = _cand("weak", B, 0.01, pf=1.05)
    lucky = _cand("lucky", B, 0.01, dsr=0.3)
    plan = al.plan([ok, few, loser, weak, lucky], 100_000, "balanced", "IN")
    assert [s["name"] for s in plan.sleeves] == ["ok"]
    why = {x["name"]: x["reason"] for x in plan.left_out}
    assert "too few trades" in why["few"]
    assert "didn't make money" in why["loser"]
    assert "won less than 1.1×" in why["weak"]
    assert "could be luck (30%" in why["lucky"]


def test_a_copycat_is_left_out() -> None:
    a = _cand("a", A, 0.01, sharpe=1.2)
    twin = _cand("twin", A, 0.02, sharpe=1.0)  # the same moves, twice as big
    plan = al.plan([a, twin], 100_000, "balanced", "IN")
    assert [s["name"] for s in plan.sleeves] == ["a"]
    assert "moves with “a” (correlation 1.00)" in plan.left_out[0]["reason"]


def test_budget_caps_reserve_and_reasons() -> None:
    cands = [_cand("a", A, 0.002), _cand("b", B, 0.002), _cand("c", C, 0.002)]
    plan = al.plan(cands, 100_000, "careful", "IN")
    invested = sum(s["capital"] for s in plan.sleeves)
    assert invested <= 80_000 + 1e-6  # careful keeps 20% in cash
    assert plan.cash == pytest.approx(100_000 - invested)
    assert all(s["capital"] <= 0.30 * 80_000 + 1e-6 for s in plan.sleeves)  # capped per sleeve
    first = plan.sleeves[0]["reasons"]
    assert first[0].startswith("Held up on unseen years") and "Luck check" in first[1]
    assert plan.public()["invested"] == pytest.approx(invested)


def test_volatility_target_keeps_more_in_cash() -> None:
    wild = [_cand("a", A, 0.03), _cand("b", B, 0.03)]  # about 48% a year each
    plan = al.plan(wild, 100_000, "balanced", "IN")
    invested = sum(s["capital"] for s in plan.sleeves)
    assert invested < 0.9 * 100_000 * 0.8  # well under the 90% it could invest
    assert plan.estimate["volatility"] <= 0.15 + 1e-6


def test_a_small_budget_drops_what_it_cant_fund() -> None:
    # 19% of the money per trade must buy one share: ₹12,450 needs 12,450 × 100/19 × 1.05
    dear = _cand("dear", A, 0.01, dearest=12_450.0, sharpe=0.8)
    cheap = _cand("cheap", B, 0.01, dearest=300.0, sharpe=1.0)
    plan = al.plan([dear, cheap], 50_000, "balanced", "IN")
    assert [s["name"] for s in plan.sleeves] == ["cheap"]
    assert "can't buy one share" in plan.left_out[0]["reason"]
    assert al.plan([dear], 50_000, "balanced", "IN").sleeves == []
    nothing = al.plan([], 50_000, "balanced", "IN")
    assert nothing.cash == 50_000 and "stays in cash" in nothing.notes[0]


def test_overlapping_stocks_are_reported() -> None:
    a = _cand("a", A, 0.01, symbols=["TCS", "INFY"])
    b = _cand("b", B, 0.01, symbols=["INFY", "HDFCBANK"])
    plan = al.plan([a, b], 100_000, "bold", "IN")
    assert plan.overlaps == ["INFY is traded by 2 sleeves (a, b)."]
