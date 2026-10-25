# Overlay analysis — residual momentum, volatility targeting, delivery veto

**Date:** 2026-10-25 · **Universe:** NIFTY 500 PIT (verified) · **Prices:** repaired + break firewall
**Window:** 2018-01-01 → 2026-08-31 · **Engine:** C99 tensor kernel · **Costs:** 15 + 5 bps

## What each overlay does (as implemented in the C kernel)

| Overlay | Mechanism | Where |
|---|---|---|
| **Residual momentum** | Blitz et al.: rolling 252-day regression of stock excess returns on benchmark excess returns, residual z-score (skip 21 days, clip ±5). Ranking becomes `0.6 × residual + 0.4 × Volar`. | `nextgen/residual_momentum.py`; cube `composite_volar_252` |
| **Volatility targeting** | EWMA (λ=0.94) benchmark vol; exposure = clip(12 % / realised vol, 0.20–1.00) × √breadth; forced 0 in a bear regime (close < 20 EMA). | `nextgen/volatility_targeting.py`; `compute_dynamic_cash_shield_scalar` in `nextgen_sim` |
| **Delivery veto** | In the Python module: Smart-Money Footprint Index from delivery quantity (veto ≤ −1.5, confirm ≥ +2.5). **In the C kernel it is simplified** to close-location value: veto if CLV < −0.70 on the signal day. | `nextgen/delivery_flow.py` vs `cube_builder.delivery_veto_plane` |

## Experiment — canonical configuration (20 / 252 / 200 / 0.80 / 2)

| R | V | D | CAGR % | Sharpe | MaxDD % | Trades |
|---|---|---|---:|---:|---:|---:|
| 0 | 0 | 0 | 19.89 | 0.706 | 28.76 | 473 |
| 0 | 0 | 1 | 20.28 | 0.711 | 29.38 | 506 |
| 0 | 1 | 0 | 17.86 | 0.632 | 28.82 | 473 |
| 0 | 1 | 1 | 18.88 | 0.668 | 29.75 | 506 |
| 1 | 0 | 0 | 18.52 | 0.717 | 19.49 | 574 |
| 1 | 0 | 1 | 17.70 | 0.673 | 19.67 | 593 |
| 1 | 1 | 0 | 17.06 | 0.651 | 18.86 | 574 |
| 1 | 1 | 1 | 15.87 | 0.592 | 19.16 | 593 |

## Experiment — best grid configuration (10 / 189 / 250 / 0.80 / 2)

| R | V | D | CAGR % | Sharpe | MaxDD % | Trades |
|---|---|---|---:|---:|---:|---:|
| 0 | 0 | 0 | 27.41 | 0.916 | 26.64 | 176 |
| 0 | 0 | 1 | 28.15 | 0.928 | 32.48 | 172 |
| 0 | 1 | 0 | 22.92 | 0.763 | 27.95 | 176 |
| 0 | 1 | 1 | 23.94 | 0.798 | 30.54 | 172 |
| 1 | 0 | 0 | 8.85 | 0.202 | 26.17 | 251 |
| 1 | 0 | 1 | 7.00 | 0.101 | 25.33 | 261 |
| 1 | 1 | 0 | 8.28 | 0.174 | 23.57 | 251 |
| 1 | 1 | 1 | 5.06 | -0.019 | 29.22 | 261 |

R = residual momentum, V = vol targeting, D = delivery veto.

## Verdict

- **Residual momentum (as implemented):** at the canonical 252-day lookback it cuts drawdown from
  28.8 % to **19.5 %** but also cuts CAGR from 19.9 % to 18.5 % (Sharpe 0.706 → 0.717). At a
  189-day lookback it is **broken** — the kernel always ranks on the fixed 252-day residual plane,
  so a 189-day strategy is compared against a mismatched factor and CAGR collapses to 8.8 %.
  Use only with lookback = 252, and as a **drawdown tool**, not a return enhancer.
- **Volatility targeting:** costs ~2 pp CAGR on both configurations and lowers Sharpe (0.706→0.632,
  0.916→0.763). A 12 % target is below the realised vol of this momentum book, so it holds cash in
  a bull market; drawdown is essentially unchanged. Not worth it at 12 %; if used at all, the target
  should be raised or applied only in high-vol regimes.
- **Delivery veto:** +0.4 pp CAGR on canonical, +0.7 pp on the best config, Sharpe +0.005/+0.012 —
  within noise, and it raises drawdown on the small book (26.6 %→32.5 %). The C proxy (CLV) is not
  the delivery-quantity SMFI the Python module computes, so this is not a fair test of that module.
- **All three together:** 15.9 % / 0.59 (canonical) and 5.1 % / −0.02 (best) — clearly worse.

**Recommendation:** keep all three **off** in production (the canonical run has the best Sharpe and
CAGR). If drawdown control is required, enable residual momentum **only at lookback 252**. Before
trusting delivery veto, port the SMFI/delivery-volume definition into the kernel.

## Appendix — long-run check (best settings)

| Universe | Window | CAGR | Sharpe | MaxDD | Trades |
|---|---|---:|---:|---:|---:|
| ALL (full cross-section) | 2012-01-01 → 2026-10-19 | 36.09% | 1.15 | 42.24% | 351 |
| NIFTY500 PIT | 2016-01-18 → 2026-10-19 | refused (insufficient PIT breadth before 2018) | — | — | — |
| NIFTY500 PIT | 2018-01-01 → 2026-08-31 | 27.41% | 0.916 | 26.64% | 176 |

The ALL run is **not** index-PIT: it trades the full 1,083-symbol cross-section (delisted names
included), so its 36.1 % CAGR / 1.15 Sharpe is a broad-universe reference, not a NIFTY 500 result.
