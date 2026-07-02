# Dynamic Param V6 Full Simulation Logic Error Report

Generated: 2026-07-02T03:43:37.943563+00:00

## Summary
- Profiles tested: 2295
- Path simulation runs: 114750
- Live symbols tested: 50
- Static profile errors: 0
- Path simulation errors: 0
- Live critical errors: 0
- Live warnings: 0

- Safe-wait null params count: 0
- PB11 loop broken count: 0
- Raw trailing display count: 0
- Fee efficiency present count: 0
- Score/class mismatch count: 0

## Critical Errors

| error_code | count | examples |
|---|---:|---|

## Strategy Logic Findings
### R2/V1 low volatility grid width
See WARN_R2_V1_* and WARN_LOW_ACTIVITY_FOR_1WEEK_BOT in warnings.
### R8/PB11 crash loop integrity
See ERROR_PB11_* and ERROR_R8_* codes.
### BTCUSDT double context
See WARN_BTCUSDT_* and ERROR_BTCUSDT_* codes.
### Asset fragility boundary
See WARN_ASSET_FRAGILITY_* codes.
### DQ / volatility score direction mismatch
See WARN_DQ_LABEL_SCORE_MISMATCH and WARN_VOLATILITY_LABEL_SCORE_MISMATCH.
### Fee remnants in V6
See ERROR_FEE_EFFICIENCY_PRESENT_IN_V6.
### Trailing quantization display
See ERROR_RAW_TRAILING_DISPLAYED and ERROR_TRAILING_NOT_IN_LATTICE.

## Live 50 Symbol Results

| symbol | regime | behavior | severity | final_profile | base/quote | buy grids | sell grids | rebuy | profit sell | workability | warnings |
|---|---|---|---|---|---|---|---|---|---|---:|---|
| 1000CHEEMSUSDT | R4 | PB02 | STD | DPLV6_R4-25-098_PB02_STD__ADJ_DQ_15_BTC_ | 20/80 | [9, 15] | [6, 13] | True | True | 100 |  |
| ACTUSDT | R8 | PB11 | DEF | DPLV6_R8-57-211_PB11_DEF__ADJ_DQ_15_BTC_ | 5/95 | [] | [6] | True | True | 100 |  |
| ADAUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_15_BTC_ | 10/90 | [11, 17] | [7, 14] | True | True | 88 |  |
| ANKRUSDT | R3 | PB01 | DEF | DPLV6_R3-17-065_PB01_DEF__ADJ_DQ_15_BTC_ | 15/85 | [] | [6] | True | True | 100 |  |
| ATOMUSDT | R3 | PB01 | DEF | DPLV6_R3-17-065_PB01_DEF__ADJ_DQ_15_BTC_ | 15/85 | [10] | [6, 10] | True | True | 100 |  |
| AVAXUSDT | R3 | PB01 | STD | DPLV6_R3-17-065_PB01_STD__ADJ_DQ_15_BTC_ | 25/75 | [5, 9] | [4, 8] | True | True | 100 |  |
| BANANAUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_15_BTC_ | 10/90 | [] | [8] | True | True | 100 |  |
| BARUSDT | R2 | PB01 | DEF | DPLV6_R2-09-033_PB01_DEF__ADJ_DQ_15_BTC_ | 15/85 | [] | [6] | True | True | 100 |  |
| BIGTIMEUSDT | R5 | PB07 | DEF | DPLV6_R5-33-129_PB07_DEF__ADJ_DQ_15_BTC_ | 15/85 | [] | [7] | True | True | 100 |  |
| BTCUSDT | R4 | PB02 | STD | DPLV6_R4-25-098_PB02_STD__ADJ_DQ_15_BTC_ | 25/75 | [8, 14] | [6, 13] | True | True | 100 |  |
| CETUSUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_15_BTC_ | 10/90 | [] | [8] | True | True | 100 |  |
| CGPTUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_15_BTC_ | 10/90 | [11, 17] | [7, 14] | True | True | 88 |  |
| DASHUSDT | R6 | PB06 | DEF | DPLV6_R6-41-161_PB06_DEF__ADJ_DQ_15_BTC_ | 5/95 | [] | [10] | True | True | 90 |  |
| EDUUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_15_BTC_ | 10/90 | [] | [8] | True | True | 100 |  |
| ESPUSDT | R8 | PB11 | DEF | DPLV6_R8-57-211_PB11_DEF__ADJ_DQ_15_BTC_ | 5/95 | [] | [6] | True | True | 100 |  |
| ETHUSDT | R4 | PB02 | STD | DPLV6_R4-25-098_PB02_STD__ADJ_DQ_15_BTC_ | 20/80 | [9, 15] | [6, 13] | True | True | 100 |  |
| FLOKIUSDT | R5 | PB07 | DEF | DPLV6_R5-33-129_PB07_DEF__ADJ_DQ_15_BTC_ | 15/85 | [9] | [6, 10] | True | True | 100 |  |
| FRAXUSDT | R1 | PB05 | DEF | DPLV6_R1-01-001_PB05_DEF__ADJ_DQ_15_BTC_ | 15/85 | [] | [7] | True | True | 100 |  |
| GLMRUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_15_BTC_ | 10/90 | [] | [9] | True | True | 100 |  |
| GMXUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_15_BTC_ | 10/90 | [12] | [8, 15] | True | True | 88 |  |
| GNSUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_15_BTC_ | 10/90 | [] | [8] | True | True | 100 |  |
| GRTUSDT | R6 | PB06 | DEF | DPLV6_R6-41-161_PB06_DEF__ADJ_DQ_15_BTC_ | 5/95 | [] | [9] | True | True | 90 |  |
| GTCUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_15_BTC_ | 10/90 | [] | [10] | True | True | 100 |  |
| GUNUSDT | R8 | PB11 | DEF | DPLV6_R8-57-211_PB11_DEF__ADJ_DQ_15_BTC_ | 5/95 | [] | [6] | True | True | 100 |  |
| HEIUSDT | R8 | PB11 | DEF | DPLV6_R8-57-211_PB11_DEF__ADJ_DQ_15_BTC_ | 5/95 | [] | [6] | True | True | 100 |  |
| INJUSDT | R4 | PB02 | STD | DPLV6_R4-25-098_PB02_STD__ADJ_DQ_15_BTC_ | 20/80 | [9, 15] | [6, 13] | True | True | 100 |  |
| KAIAUSDT | R3 | PB01 | DEF | DPLV6_R3-17-065_PB01_DEF__ADJ_DQ_15_BTC_ | 15/85 | [] | [6] | True | True | 100 |  |
| LQTYUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_15_BTC_ | 10/90 | [] | [8] | True | True | 100 |  |
| MANTAUSDT | R8 | PB11 | STD | DPLV6_R8-57-211_PB11_STD__ADJ_DQ_15_BTC_ | 5/95 | [] | [8] | True | True | 100 |  |
| MUBUSDT | R8 | PB11 | DEF | DPLV6_R8-57-211_PB11_DEF__ADJ_DQ_15_BTC_ | 5/95 | [] | [6] | True | True | 100 |  |
| NIGHTUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_15_BTC_ | 10/90 | [12] | [8, 15] | True | True | 88 |  |
| NXPCUSDT | R1 | PB05 | DEF | DPLV6_R1-01-001_PB05_DEF__ADJ_DQ_15_BTC_ | 15/85 | [10] | [7, 12] | True | True | 100 |  |
| OPNUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_15_BTC_ | 10/90 | [11, 17] | [7, 14] | True | True | 88 |  |
| ORDIUSDT | R8 | PB11 | DEF | DPLV6_R8-57-211_PB11_DEF__ADJ_DQ_15_BTC_ | 5/95 | [] | [6] | True | True | 100 |  |
| OSMOUSDT | R3 | PB01 | DEF | DPLV6_R3-17-065_PB01_DEF__ADJ_DQ_15_BTC_ | 15/85 | [] | [6] | True | True | 100 |  |
| QIUSDT | R8 | PB11 | DEF | DPLV6_R8-57-211_PB11_DEF__ADJ_DQ_15_BTC_ | 5/95 | [] | [6] | True | True | 100 |  |
| REUSDT | R8 | PB11 | STD | DPLV6_R8-57-211_PB11_STD__ADJ_DQ_15_BTC_ | 5/95 | [] | [8] | True | True | 100 |  |
| REZUSDT | R6 | PB06 | DEF | DPLV6_R6-41-161_PB06_DEF__ADJ_DQ_15_BTC_ | 5/95 | [] | [11] | True | True | 90 |  |
| RLCUSDT | R1 | PB05 | DEF | DPLV6_R1-01-001_PB05_DEF__ADJ_DQ_30_BTC_ | 15/85 | [] | [7] | True | True | 100 |  |
| SOLUSDT | R4 | PB02 | STD | DPLV6_R4-25-098_PB02_STD__ADJ_DQ_30_BTC_ | 20/80 | [9, 15] | [6, 13] | True | True | 100 |  |
| SPKUSDT | R3 | PB01 | DEF | DPLV6_R3-17-065_PB01_DEF__ADJ_DQ_30_BTC_ | 15/85 | [] | [6] | True | True | 100 |  |
| SUNUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_30_BTC_ | 10/90 | [11, 17] | [7, 14] | True | True | 88 |  |
| SYNUSDT | R8 | PB11 | DEF | DPLV6_R8-57-211_PB11_DEF__ADJ_DQ_30_BTC_ | 5/95 | [] | [6] | True | True | 100 |  |
| TAOUSDT | R4 | PB02 | STD | DPLV6_R4-25-098_PB02_STD__ADJ_DQ_30_BTC_ | 20/80 | [9, 15] | [6, 13] | True | True | 100 |  |
| UNIUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_30_BTC_ | 10/90 | [11, 17] | [7, 14] | True | True | 88 |  |
| USTCUSDT | R6 | PB06 | DEF | DPLV6_R6-41-161_PB06_DEF__ADJ_DQ_30_BTC_ | 5/95 | [] | [10] | True | True | 90 |  |
| VICUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_30_BTC_ | 10/90 | [15] | [10, 17] | True | True | 100 |  |
| WIFUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_30_BTC_ | 10/90 | [11, 17] | [7, 14] | True | True | 88 |  |
| YBUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_30_BTC_ | 10/90 | [] | [9] | True | True | 100 |  |
| YGGUSDT | R4 | PB02 | DEF | DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_30_BTC_ | 10/90 | [] | [9] | True | True | 100 |  |

## Recommended Fixes by Priority

### P0
- ERROR_SAFE_WAIT_NULL_PARAMS — V6 must always return params
- ERROR_PB11_LOOP_BROKEN — preserve post-sell rebuy + profit sell on crash profiles

### P1
- WARN_LOW_ACTIVITY_FOR_1WEEK_BOT — tighten R2/V1 grids for 1-week bots
- ERROR_R8_BUY_GRID_TOO_CLOSE — deepen or disable buys in crash regimes

### P2
- WARN_BTCUSDT_DOUBLE_CONTEXT — verify btc_context_delta_multiplier 0.5 on BTCUSDT
- ERROR_FEE_EFFICIENCY_PRESENT_IN_V6 — strip V5 fee artifacts from telemetry

### P3
- WARN_GRID_TOO_WIDE / WARN_GRID_TOO_NARROW — regime-volatility tuning

## Priority Table

| Öncelik | Hata | Etki | Örnek | Çözüm |
|---|---|---|---|---|
| P0 | safe_wait params=None | Parametre ekranı bozulur | R8/F3/V5 | V6 always-return params |
| P1 | R2/V1 grid fazla geniş | 1 haftalık bot pasif kalır | AVAXUSDT | grid contraction rule |
| P1 | PB11 loop broken | Crash sonrası kar döngüsü kapanır | PB11 DEF | decouple from normal_buy |
| P2 | BTCUSDT double penalty | Aşırı savunmacı BTC | BTCUSDT | btc_context_delta_multiplier |
