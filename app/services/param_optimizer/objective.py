"""
Hedef fonksiyon: KÂR + SAĞLAMLIK + İŞLEM SIKLIĞI dengesi.

Kullanıcı tercihi (4 soruluk netleştirme):
  * Birincil eksen: OOS üzerinde net kâr (aylık normalize) — IS değil.
  * İşlem sıklığı: yeterli tur/işlem üretmeli — tek bir "şanslı" işlemle yüksek
    getiri yapan setler elenir; aşırı seyrek tur cezalandırılır.
  * Drawdown: yalnız patlama önleyici hafif guard (tavanı aşınca ceza).
  * Son 1 yıl ağırlıklı + OOS (son ~6 ay) doğrulama -> ezber/overfit engeli.

Sağlamlık eklemeleri (v2):
  * DEJENERELİK BARAJI: IS'te sıfır kayıp (PF>=50) → skor=-1e6 (anlık elim).
  * ÇOKLANMIŞ OVERFIT CEZASI: overfit_penalty_weight 0.4 → 1.8.
  * OOS AĞIRLIĞI: 0.6 → 0.78 (IS artık sadece tiebreaker düzeyinde).
  * OOS TABAN CEZASI: OOS aylık getiri < -2% → her yüzde puanı için ek ceza.
  * IS AŞIRI GETIRI ISKONTO: IS aylık > 8% → "gerçek mi?" iskonto uygula.
  * HONEST-ALPHA BONUSU AĞIRLIĞI: 0.12 → 0.25 (pasif tutmayı yenmeye güçlü baskı).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.services.param_optimizer.backtest import BacktestResult

# ─── Dejenerelik sınırları ───────────────────────────────────────────────────
# IS'te bu kadar yüksek PF → zaten overfit (hiç kayıp yok veya çok az).
# Optimizer bu seti ANLARSIZ bulur; rastgele yeniden başlamasına gerek kalmaz.
_PF_DEGENERATE = 50.0          # bu PF'nin üstündeki IS backtest'leri reddedilir
_DEGENERATE_SCORE = -1_000_000.0

# OOS aylık getiri bu kadar altındaysa ek taban cezası
_OOS_FLOOR_MONTHLY_PCT = -2.0
_OOS_FLOOR_PENALTY_PER_PCT = 0.5   # her ek yüzde puanı için aylık-% ceza

# IS aylık getiri bu kadarın üstündeyse gerçekçilik iskonto başlar
_IS_SUSPECT_MONTHLY_PCT = 8.0
_IS_SUSPECT_DISCOUNT = 0.55        # skor * bu ile çarp (fazla parlak IS'i söndür)


@dataclass
class ObjectiveConfig:
    target_cycles_per_month: float = 1.5   # uzun vadeli botta sağlıklı tur sıklığı
    min_cycles_floor: int = 2              # altında ağır indirim
    freq_bonus_weight: float = 0.18        # aktivite bonusu (aylık % cinsinden)
    dd_cap_pct: float = 35.0              # bunun üstü drawdown cezalı
    dd_penalty_weight: float = 0.05        # % başına ceza (aylık %)
    blowup_dd_pct: float = 60.0           # felaket eşiği
    blowup_penalty: float = 50.0
    idle_penalty: float = 6.0             # hiç tur kapatmayan (pasif) set cezası

    # ── OOS ağırlığı artırıldı: 0.6 → 0.78 ────────────────────────────────
    oos_weight: float = 0.78              # nihai skorda OOS payı (dominant)
    in_sample_weight: float = 0.22        # IS artık tiebreaker düzeyinde
    recent_in_weight: float = 0.5         # in-sample içinde son yıl ek ağırlığı

    # ── Overfit cezası güçlendirildi: 0.4 → 1.8 ───────────────────────────
    overfit_penalty_weight: float = 1.8   # in-sample >> oos ise çok daha sert ceza

    # MARUZİYET KAYMASI
    exposure_drift_cap: float = 0.10      # bu fraction'a kadar kayma tolere edilir
    exposure_drift_penalty_weight: float = 0.10  # aşan her yüzde puanı için aylık-% ceza

    # DÜRÜST KIYAS — ağırlık artırıldı: 0.12 → 0.25 ───────────────────────
    honest_alpha_weight: float = 0.25     # pasif tutmayı yenmeye güçlü teşvik


def _smoothstep(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 1.0 if x >= hi else 0.0
    t = max(0.0, min(1.0, (x - lo) / (hi - lo)))
    return t * t * (3.0 - 2.0 * t)


def _is_degenerate(r: BacktestResult) -> bool:
    """IS backtest'in gerçek bir stratejinin ürütemeyeceği kadar 'mükemmel' olup
    olmadığını kontrol et. PF >= 50 → sıfır veya ihmal edilebilir kayıp → overfit."""
    pf = getattr(r, "profit_factor", 0.0) or 0.0
    return pf >= _PF_DEGENERATE


@dataclass
class ScoreBreakdown:
    score: float = 0.0
    monthly_return_pct: float = 0.0
    return_pct: float = 0.0
    activity_factor: float = 0.0
    freq_bonus: float = 0.0
    dd_penalty: float = 0.0
    idle_penalty: float = 0.0
    exposure_drift_penalty: float = 0.0
    honest_alpha_bonus: float = 0.0
    oos_floor_penalty: float = 0.0
    degenerate: bool = False
    cycles_per_month: float = 0.0
    cycles_closed: int = 0
    max_drawdown_pct: float = 0.0
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            k: (round(v, 4) if isinstance(v, float) else v)
            for k, v in self.__dict__.items()
        }


def score_backtest(
    r: BacktestResult,
    cfg: ObjectiveConfig = None,
    *,
    is_oos: bool = False,
) -> ScoreBreakdown:
    """Tek bir backtest sonucunu skorla (aylık % ölçeğinde).

    is_oos=True ise OOS'a özgü taban cezası uygulanır; False ise IS dejenerelik
    bariyeri kontrol edilir.
    """
    cfg = cfg or ObjectiveConfig()
    b = ScoreBreakdown()
    if not r or not r.ok:
        b.score = -1e9
        b.note = "invalid"
        return b

    # ── DEJENERELİK BARAJI (sadece IS için) ─────────────────────────────────
    if not is_oos and _is_degenerate(r):
        pf = getattr(r, "profit_factor", 0.0) or 0.0
        b.score = _DEGENERATE_SCORE
        b.degenerate = True
        b.note = f"degenerate_pf={pf:.1f}"
        # Gerçek metrikleri yine de doldur (karar katmanı için)
        b.return_pct = r.return_pct
        b.cycles_closed = r.cycles_closed
        b.max_drawdown_pct = r.max_drawdown_pct
        return b

    months = max(0.5, r.days / 30.4375)
    monthly_ret = r.return_pct / months
    b.return_pct = r.return_pct
    b.monthly_return_pct = monthly_ret
    b.cycles_per_month = r.cycles_per_month
    b.cycles_closed = r.cycles_closed
    b.max_drawdown_pct = r.max_drawdown_pct

    # Aktivite faktörü: 0 tur -> 0, hedefe doğru 1'e yaklaşır
    activity = _smoothstep(
        r.cycles_closed,
        cfg.min_cycles_floor,
        max(cfg.min_cycles_floor + 1, cfg.target_cycles_per_month * months),
    )
    b.activity_factor = activity

    # Kâr terimi aktiviteyle modüle edilir: az tur => kâra güvenme (şanslı olabilir)
    profit_term = monthly_ret * (0.45 + 0.55 * activity)

    # ── IS AŞIRI GETIRI İSKONTOSU ────────────────────────────────────────────
    # IS'te "fazla parlak" (aylık >8%) setler gerçekçilik testi geçemez; bunu söndür.
    if not is_oos and monthly_ret > _IS_SUSPECT_MONTHLY_PCT:
        profit_term *= _IS_SUSPECT_DISCOUNT
        b.note = f"is_suspect_discount (monthly={monthly_ret:.1f}%)"

    # Sağlıklı tur sıklığı bonusu (doyumlu)
    freq = _smoothstep(r.cycles_per_month, 0.5, cfg.target_cycles_per_month)
    b.freq_bonus = cfg.freq_bonus_weight * freq

    # Drawdown cezası (sadece tavan üstü)
    dd_over = max(0.0, r.max_drawdown_pct - cfg.dd_cap_pct)
    b.dd_penalty = cfg.dd_penalty_weight * dd_over
    if r.max_drawdown_pct >= cfg.blowup_dd_pct:
        b.dd_penalty += cfg.blowup_penalty

    # Düşük-aktivite cezası
    sparse = 1.0 - _smoothstep(r.cycles_closed, 0.0, float(cfg.min_cycles_floor))
    b.idle_penalty = cfg.idle_penalty * sparse

    # Maruziyet kayması cezası
    drift_over = max(0.0, abs(getattr(r, "exposure_drift", 0.0)) - cfg.exposure_drift_cap)
    b.exposure_drift_penalty = cfg.exposure_drift_penalty_weight * (drift_over * 100.0)

    # Dürüst-alpha ödülü (ağırlık artırıldı)
    honest_alpha_monthly = getattr(r, "grid_alpha_vs_intended_pct", 0.0) / months
    b.honest_alpha_bonus = cfg.honest_alpha_weight * honest_alpha_monthly

    # ── OOS TABAN CEZASI ─────────────────────────────────────────────────────
    # OOS aylık getiri _OOS_FLOOR'un altındaysa her yüzde puanı için ek ceza.
    if is_oos and monthly_ret < _OOS_FLOOR_MONTHLY_PCT:
        oos_below = _OOS_FLOOR_MONTHLY_PCT - monthly_ret  # pozitif değer
        b.oos_floor_penalty = _OOS_FLOOR_PENALTY_PER_PCT * oos_below
    else:
        b.oos_floor_penalty = 0.0

    b.score = (
        profit_term
        + b.freq_bonus
        + b.honest_alpha_bonus
        - b.dd_penalty
        - b.idle_penalty
        - b.exposure_drift_penalty
        - b.oos_floor_penalty
    )
    return b


def combined_score(
    in_sample: BacktestResult,
    oos: Optional[BacktestResult] = None,
    recent_in: Optional[BacktestResult] = None,
    cfg: ObjectiveConfig = None,
) -> Dict[str, Any]:
    """
    Nihai skor: IS + OOS birleşimi.

      * OOS dominant (ağırlık 0.78): sağlam parametre seçiminin tek yolu görülmemiş
        veride tutarlı performanstır.
      * IS'te dejenere (PF>=50) → anlık -1e6: optimizer bu setten kaçar.
      * Overfit cezası 1.8x: IS>>OOS uçurumu çok daha sert cezalandırılır.
      * IS'te aylık >8% → iskonto: "fazla parlak" IS seti tercih edilmez.
      * recent_in (IS'in son 1 yılı) varsa in-sample skoru recency ile harman.
    """
    cfg = cfg or ObjectiveConfig()

    # IS skoru (dejenere ise -1e6)
    s_in = score_backtest(in_sample, cfg, is_oos=False)

    # IS dejenere ise doğrudan döndür (OOS hesaplamaya gerek yok)
    if s_in.degenerate:
        return {
            "final_score": _DEGENERATE_SCORE,
            "in_sample_score": _DEGENERATE_SCORE,
            "in_sample": s_in.to_dict(),
            "recent_in": None,
            "oos": None,
            "degenerate": True,
        }

    if recent_in is not None:
        s_rec = score_backtest(recent_in, cfg, is_oos=False)
        in_score = (
            1 - cfg.recent_in_weight
        ) * s_in.score + cfg.recent_in_weight * s_rec.score
    else:
        s_rec = None
        in_score = s_in.score

    if oos is not None:
        s_oos = score_backtest(oos, cfg, is_oos=True)
        # overfit_gap: IS çok iyiyse OOS'tan bu kadar iyi olmayı bekliyorduk
        overfit_gap = max(0.0, in_score - s_oos.score)
        final = (
            cfg.in_sample_weight * in_score
            + cfg.oos_weight * s_oos.score
            - cfg.overfit_penalty_weight * overfit_gap
        )
    else:
        s_oos = None
        final = in_score

    return {
        "final_score": final,
        "in_sample_score": in_score,
        "in_sample": s_in.to_dict(),
        "recent_in": s_rec.to_dict() if s_rec else None,
        "oos": s_oos.to_dict() if s_oos else None,
        "degenerate": False,
    }
