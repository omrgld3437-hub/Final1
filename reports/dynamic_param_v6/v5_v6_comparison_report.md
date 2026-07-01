# Dynamic Param V5/V6 Staging Comparison Report

Generated: 2026-07-01T19:11:33.591497+00:00
Budget: 500.0 USDT

## Acceptance summary

- Staging V6 all OK: **True**
- V5 removal ready: **True** (manual sign-off still required)

## Per-symbol comparison

### BTCUSDT

| Field | V5 | V6 |
|-------|----|----|
| Route / shelf | `A1|R2|D1|S4|V2|K1|L2` / `DPLV5_A1_R2_D1_S4_V2_K1_L2` | scenario `R6-41-161` |
| Base / quote | 45.5/54.5 | 5/95 |
| Buy grids | buy: · sell: | [] |
| Sell grids | — | [9] |
| Profit / trailing | rebuy=True@2.28/0.3 resell=True@2.28/0.33 trail=0.405 | enabled=True trigger=7.0 trail=1.1 · enabled=True trigger=6.5 trail=1.4 |
| Fee behavior | friction=None | none (cost floor only) |
| Behavior / severity | — | PB06 / DEF |
| profile_id | — | `DPLV6_R6-41-161_T553_PB06_DEF` |
| final_profile_id | — | `DPLV6_R6-41-161_PB06_DEF__ADJ_DQ_15_BTC_B1_F_F2_V1_L1_FINAL` |
| Adjuster trace | — | data_quality:DQ0, btc_context:B1, asset_fragility:F2, volatility:V1, liquidity:L1, support_resistance:SR_NEUTRAL, fake_move:FM_NEUTRAL, delta_limiter:CAPPED, budget_scaler:PASS, exchange_validator:PAS |
| V6 validation | — | OK=True errors=[] |

**Decision:** V6 daha doğru
**Reason:** V5 bekle/engel iken V6 katalog profili üretti

### ETHUSDT

| Field | V5 | V6 |
|-------|----|----|
| Route / shelf | `A2|R4|D2|S5|V3|K2|L2` / `DPLV5_A2_R4_D2_S5_V3_K2_L2` | scenario `R4-25-098` |
| Base / quote | 48.0/52.0 | 20/80 |
| Buy grids | buy: · sell: | [9, 15] |
| Sell grids | — | [6, 13] |
| Profit / trailing | rebuy=True@2.8/0.72 resell=True@2.8/0.55 trail=0.7776 | enabled=True trigger=6.0 trail=1.1 · enabled=True trigger=6.0 trail=1.4 |
| Fee behavior | friction=None | none (cost floor only) |
| Behavior / severity | — | PB02 / STD |
| profile_id | — | `DPLV6_R4-25-098_T364_PB02_STD` |
| final_profile_id | — | `DPLV6_R4-25-098_PB02_STD__ADJ_DQ_15_BTC_B1_F_F1_V2_L0_FINAL` |
| Adjuster trace | — | data_quality:DQ0, btc_context:B1, asset_fragility:F1, volatility:V2, liquidity:L0, support_resistance:SR_NEUTRAL, fake_move:FM_NEUTRAL, delta_limiter:CAPPED, budget_scaler:PASS, exchange_validator:PAS |
| V6 validation | — | OK=True errors=[] |

**Decision:** V6 daha doğru
**Reason:** V5 bekle/engel iken V6 katalog profili üretti

### MANTAUSDT

| Field | V5 | V6 |
|-------|----|----|
| Route / shelf | `A4|R12|D1|S8|V4|K1|L2` / `DPLV5_A4_R12_D1_S8_V4_K1_L2` | scenario `R8-57-211` |
| Base / quote | 21.1/78.9 | 5/95 |
| Buy grids | buy: · sell: | [] |
| Sell grids | — | [9] |
| Profit / trailing | rebuy=True@3.28/0.86 resell=True@3.28/0.64 trail=0.9288 | enabled=True trigger=5.5 trail=1.1 · enabled=True trigger=6.0 trail=1.1 |
| Fee behavior | friction=None | none (cost floor only) |
| Behavior / severity | — | PB11 / STD |
| profile_id | — | `DPLV6_R8-57-211_T705_PB11_STD` |
| final_profile_id | — | `DPLV6_R8-57-211_PB11_STD__ADJ_DQ_15_BTC_B1_F_F1_V3_L0_FINAL` |
| Adjuster trace | — | data_quality:DQ0, btc_context:B1, asset_fragility:F1, volatility:V3, liquidity:L0, support_resistance:SR_NEUTRAL, fake_move:FM_NEUTRAL, delta_limiter:CAPPED, budget_scaler:PASS, exchange_validator:PAS |
| V6 validation | — | OK=True errors=[] |

**Decision:** V6 daha doğru
**Reason:** V5 bekle/engel iken V6 katalog profili üretti

### SYNUSDT

| Field | V5 | V6 |
|-------|----|----|
| Route / shelf | `A4|R8|D3|S5|V5|K1|L2` / `DPLV5_A4_R8_D3_S5_V5_K1_L2` | scenario `R8-57-211` |
| Base / quote | 5.0/95.0 | 5/95 |
| Buy grids | buy: · sell:+7.6%/100% | [] |
| Sell grids | — | [9] |
| Profit / trailing | rebuy=True@3.61/1.3 resell=True@3.61/0.75 trail=1.404 | enabled=True trigger=5.5 trail=1.1 · enabled=True trigger=6.0 trail=1.1 |
| Fee behavior | friction=None | none (cost floor only) |
| Behavior / severity | — | PB11 / STD |
| profile_id | — | `DPLV6_R8-57-211_T705_PB11_STD` |
| final_profile_id | — | `DPLV6_R8-57-211_PB11_STD__ADJ_DQ_15_BTC_B1_F_F1_V3_L0_FINAL` |
| Adjuster trace | — | data_quality:DQ0, btc_context:B1, asset_fragility:F1, volatility:V3, liquidity:L0, support_resistance:SR_NEUTRAL, fake_move:FM_NEUTRAL, delta_limiter:CAPPED, budget_scaler:PASS, exchange_validator:PAS |
| V6 validation | — | OK=True errors=[] |

**Decision:** V6 daha doğru
**Reason:** PB11 crash: normal alış kapalı, post-sell rebuy açık (V5 bu deseni garanti etmez)

### ADAUSDT

| Field | V5 | V6 |
|-------|----|----|
| Route / shelf | `A3|R2|D1|S5|V3|K2|L2` / `DPLV5_A3_R2_D1_S5_V3_K2_L2` | scenario `R4-25-098` |
| Base / quote | 51.8/48.2 | 10/90 |
| Buy grids | buy: · sell: | [11, 17] |
| Sell grids | — | [7, 14] |
| Profit / trailing | rebuy=True@2.4/0.67 resell=True@2.4/0.57 trail=0.7236 | enabled=True trigger=7.0 trail=1.4 · enabled=True trigger=7.0 trail=1.4 |
| Fee behavior | friction=None | none (cost floor only) |
| Behavior / severity | — | PB02 / DEF |
| profile_id | — | `DPLV6_R4-25-098_T364_PB02_DEF` |
| final_profile_id | — | `DPLV6_R4-25-098_PB02_DEF__ADJ_DQ_15_BTC_B1_F_F2_V2_L1_FINAL` |
| Adjuster trace | — | data_quality:DQ0, btc_context:B1, asset_fragility:F2, volatility:V2, liquidity:L1, support_resistance:SR_NEUTRAL, fake_move:FM_NEUTRAL, delta_limiter:CAPPED, budget_scaler:PASS, exchange_validator:PAS |
| V6 validation | — | OK=True errors=[] |

**Decision:** V6 daha doğru
**Reason:** V5 bekle/engel iken V6 katalog profili üretti

### REUSDT

| Field | V5 | V6 |
|-------|----|----|
| Route / shelf | `A4|R8|D3|S5|V4|K1|L1` / `DPLV5_A4_R8_D3_S5_V4_K1_L1` | scenario `R8-57-211` |
| Base / quote | 5.0/95.0 | 5/95 |
| Buy grids | buy: · sell:+6.39%/100% | [] |
| Sell grids | — | [8] |
| Profit / trailing | rebuy=True@3.9/1.12 resell=True@3.9/0.65 trail=1.2096 | enabled=True trigger=5.0 trail=1.1 · enabled=True trigger=5.5 trail=1.1 |
| Fee behavior | friction=None | none (cost floor only) |
| Behavior / severity | — | PB11 / STD |
| profile_id | — | `DPLV6_R8-57-211_T705_PB11_STD` |
| final_profile_id | — | `DPLV6_R8-57-211_PB11_STD__ADJ_DQ_15_BTC_B1_F_F0_V2_L0_FINAL` |
| Adjuster trace | — | data_quality:DQ0, btc_context:B1, asset_fragility:F0, volatility:V2, liquidity:L0, support_resistance:SR_NEUTRAL, fake_move:FM_NEUTRAL, delta_limiter:CAPPED, budget_scaler:PASS, exchange_validator:PAS |
| V6 validation | — | OK=True errors=[] |

**Decision:** V6 daha doğru
**Reason:** PB11 crash: normal alış kapalı, post-sell rebuy açık (V5 bu deseni garanti etmez)

## PB11 / post-sell buyback check

- MANTAUSDT: normal_buy=False buy_count=0 rebuy=True · enabled=True trigger=5.5 trail=1.1
- SYNUSDT: normal_buy=False buy_count=0 rebuy=True · enabled=True trigger=5.5 trail=1.1
- REUSDT: normal_buy=False buy_count=0 rebuy=True · enabled=True trigger=5.0 trail=1.1

## Notes

- V5 **not removed** in this pass; removal PR: `remove-dynamic-param-v5-after-v6-staging-validation`
- Set staging: `export DPS_ENGINE_VERSION=v6` (varsayılan; V5 kaldırıldı)

## V5 removal (2026-07-01)

Dynamic Param V5 runtime removed on branch `remove-dynamic-param-v5-after-v6-staging-validation`.
- `app/services/dynamic_param_score/v5/` deleted
- `DPS_ENGINE_VERSION` defaults to `v6`; `v5` raises `RuntimeError`
- Post-removal validation: `python3 tools/dynamic_param_v6/staging_v6_validation.py` → staging V6 all OK: True