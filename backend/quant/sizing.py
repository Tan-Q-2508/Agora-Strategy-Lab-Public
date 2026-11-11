"""How big to bet (METIS §11, PORTFOLIO §4).

- ``kelly``: the growth-optimal fraction for returns with this mean and variance, μ ÷ σ²
  (Kelly, 1956; Thorp). Real traders use half or less, because μ is never known precisely and
  full Kelly's drawdowns are brutal.
- ``kelly_from_trades``: the same for a win/loss bet: p − (1 − p) ÷ b, with b = average win ÷
  average loss.
- ``vol_target``: scale exposure so expected volatility matches a target (Moreira and Muir,
  2017: volatility-managed portfolios), never above ``most``.
"""

from __future__ import annotations


def kelly(mean: float, var: float) -> float:
    return mean / var if var > 0 else 0.0


def kelly_from_trades(win_rate: float, payoff: float) -> float:
    if payoff <= 0:
        return 0.0
    return win_rate - (1.0 - win_rate) / payoff


def vol_target(vol: float, target: float, most: float = 1.0) -> float:
    if vol <= 0:
        return most
    return min(most, target / vol)
