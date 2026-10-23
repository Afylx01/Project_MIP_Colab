import sys, json, math, hashlib, tempfile, shutil, time
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
sys.path.insert(0, str(ROOT))
OUT = {}

def close(a, b, tol=1e-6):
    return abs(float(a) - float(b)) <= tol

# ---------------------------------------------------------------- risk suite
from analytics.institutional_risk import calculate_comprehensive_risk_suite

bt = json.load(open(str(ROOT / "reports" / "analysis_evidence" / "04_backtest.json")))
r = np.asarray(bt["monthly_returns"], dtype=float)

bm = pd.read_csv(ROOT / "data/benchmark_nifty500.csv")
bm["date"] = pd.to_datetime(bm["date"])
bm = bm[(bm["date"] >= "2016-01-01") & (bm["date"] <= "2026-08-31")]
bm_month = bm.set_index("date")["close"].resample("ME").last().dropna()
bm_r = bm_month.pct_change().dropna().to_numpy()

suite = calculate_comprehensive_risk_suite(
    pd.Series(r), equity_curve=pd.Series(np.cumprod(1 + r)),
    benchmark_returns=pd.Series(bm_r[:len(r)]), rf_rate=0.065, annualization_factor=12)

eq = np.cumprod(1 + r)
peak = np.maximum.accumulate(eq)
dd = (eq - peak) / peak

def indep():
    cagr = float(np.prod(1 + r) ** (12.0 / len(r)) - 1.0)
    vol = float(np.std(r, ddof=1) * math.sqrt(12))
    v95 = float(-np.percentile(r, 5)); v99 = float(-np.percentile(r, 1))
    cv95 = float(-np.mean(r[r <= -v95])) if (r <= -v95).any() else v95
    cv99 = float(-np.mean(r[r <= -v99])) if (r <= -v99).any() else v99
    maxdd = float(abs(dd.min()))
    calmar = cagr / maxdd if maxdd > 1e-6 else 0.0
    ulcer = float(np.sqrt(np.mean((dd * 100) ** 2)))
    thr = 0.065 / 12
    omega = float(np.maximum(r - thr, 0).sum() / max(np.maximum(thr - r, 0).sum(), 1e-8))
    gpr = float(np.maximum(r, 0).sum() / max(np.abs(np.minimum(r, 0)).sum(), 1e-8))
    tr = float(abs(np.percentile(r, 95)) / abs(np.percentile(r, 5)))
    bmx = bm_r[:len(r)]
    beta = float(np.cov(r, bmx)[0, 1] / np.cov(r, bmx)[1, 1])
    alpha = float((np.mean(r) - beta * np.mean(bmx)) * 12)
    corr = float(np.corrcoef(r, bmx)[0, 1])
    return dict(cagr=cagr, vol=vol, v95=v95, v99=v99, cv95=cv95, cv99=cv99,
                maxdd=maxdd, calmar=calmar, ulcer=ulcer, omega=omega, gpr=gpr,
                tail=tr, beta=beta, alpha=alpha, r2=corr ** 2)

i = indep()
OUT["risk_suite"] = {
    "inputs": {"returns": len(r), "benchmark_returns": len(bm_r), "annualization": 12},
    "checks": {
        "cagr": close(suite["cagr"], i["cagr"], 1e-4),
        "vol": close(suite["annualized_volatility"], i["vol"], 1e-4),
        "var95": close(suite["var_95"], i["v95"], 1e-4),
        "var99": close(suite["var_99"], i["v99"], 1e-4),
        "cvar95": close(suite["cvar_95"], i["cv95"], 1e-4),
        "cvar99": close(suite["cvar_99"], i["cv99"], 1e-4),
        "maxdd": close(suite["max_drawdown"], i["maxdd"], 1e-4),
        "calmar": close(suite["calmar_ratio"], i["calmar"], 1e-2),
        "ulcer": close(suite["ulcer_index"], i["ulcer"], 1e-2),
        "omega": close(suite["omega_ratio"], i["omega"], 1e-2),
        "gain_to_pain": close(suite["gain_to_pain_ratio"], i["gpr"], 1e-2),
        "tail_ratio": close(suite["tail_ratio"], i["tail"], 1e-2),
        "beta": close(suite["beta"], i["beta"], 1e-2),
        "alpha_ann": close(suite["alpha_annualized"], i["alpha"], 1e-4),
        "r_squared": close(suite["r_squared"], i["r2"], 1e-4),
    },
    "reported": {k: suite[k] for k in ("cagr", "annualized_volatility", "var_95", "cvar_95",
                                       "ulcer_index", "omega_ratio", "beta", "alpha_annualized",
                                       "r_squared", "tracking_error", "information_ratio")},
    "independent": {k: round(v, 6) for k, v in i.items()},
}

# ---------------------------------------------------------------- Brinson
from analytics.factor_attribution import BrinsonFachlerEngine

P_W = {"A": 0.6, "B": 0.4}; P_R = {"A": 0.10, "B": 0.02}
B_W = {"A": 0.5, "B": 0.5}; B_R = {"A": 0.08, "B": 0.04}
one = BrinsonFachlerEngine.compute_single_period(P_W, P_R, B_W, B_R)
port = sum(P_W[k] * P_R[k] for k in P_W)
bench = sum(B_W[k] * B_R[k] for k in B_W)
active = port - bench
sums = one[["allocation_effect", "selection_effect", "interaction_effect", "total_active_return"]].sum().to_dict()

p2 = BrinsonFachlerEngine.compute_single_period(
    {"A": 0.6, "B": 0.4}, {"A": -0.03, "B": -0.005},
    {"A": 0.5, "B": 0.5}, {"A": -0.015, "B": -0.005})
two = BrinsonFachlerEngine.link_multi_period_menchero(
    [one, p2], [0.068, -0.02], [0.06, -0.01])
linked_active = float(two["cumulative_total_active"].sum())
expected_active = (1.068 * 0.98 - 1) - (1.06 * 0.99 - 1)

OUT["brinson"] = {
    "single_period": {
        "portfolio_return": round(port, 6), "benchmark_return": round(bench, 6),
        "active": round(active, 6), "attribution_sum": round(sums["total_active_return"], 6),
        "allocation": round(sums["allocation_effect"], 6),
        "selection": round(sums["selection_effect"], 6),
        "interaction": round(sums["interaction_effect"], 6),
        "identity_ok": close(sums["total_active_return"], active, 1e-5),
        "expected_allocation": 0.004, "expected_selection": 0.0, "expected_interaction": 0.004,
    },
    "multi_period": {
        "linked_active": round(linked_active, 6),
        "compounded_active_bench": round(expected_active, 6),
        "identity_ok": close(linked_active, expected_active, 1e-5),
        "rows": int(len(two)),
    },
}

# ---------------------------------------------------------------- liquidity
from analytics.liquidity_analytics import compute_liquidity_profile
from core.data_engine import load_bars

scan = json.load(open(str(ROOT / "reports" / "analysis_evidence" / "02_scan.json")))
picks = scan["picks"][:10]
orders = pd.DataFrame({
    "symbol": [p["symbol"] for p in picks],
    "close": [p["close"] for p in picks],
    "vol_252": [abs(p["ret_252"] / p["volar"]) if p["volar"] else 0.35 for p in picks],
})
orders["target_qty"] = (100000.0 / orders["close"]).astype(int)
orders["target_val"] = orders["target_qty"] * orders["close"]
bars = load_bars(start_date="2026-08-01", end_date="2026-10-19", symbols=orders.symbol.tolist())
liq = compute_liquidity_profile(orders, bars_df=bars, capital_inr=1_000_000.0)

row0 = liq["detailed_table"].iloc[0]
sym0 = row0["symbol"]
b0 = bars[bars.symbol == sym0].sort_values("date").tail(30)
exp_adv = float(b0["volume"].mean())
exp_adtv = float((b0["volume"] * b0["close"]).mean() / 1e7)
exp_dl = float(orders.loc[orders.symbol == sym0, "target_qty"].iloc[0] / (0.10 * exp_adv))
exp_part = float(orders.loc[orders.symbol == sym0, "target_qty"].iloc[0] / exp_adv * 100)

OUT["liquidity"] = {
    "portfolio_days_to_liquidate": liq["portfolio_days_to_liquidate"],
    "weighted_adv_participation_pct": liq["weighted_adv_participation_pct"],
    "strategy_capacity_crores": liq["strategy_capacity_crores"],
    "tiers": liq["liquidity_bucket_distribution"],
    "first_symbol": sym0,
    "checks": {
        "adv_match": close(row0["adv_30"], exp_adv, 1.0),
        "adtv_match": close(row0["adtv_30_cr"], exp_adtv, 0.01),
        "days_to_liq_match": close(row0["days_to_liquidate"], exp_dl, 0.02),
        "participation_match": close(row0["adv_participation_pct"], exp_part, 0.01),
    },
    "observed": {"adv_30": float(row0["adv_30"]), "adtv_30_cr": float(row0["adtv_30_cr"]),
                 "days_to_liquidate": float(row0["days_to_liquidate"]),
                 "participation_pct": float(row0["adv_participation_pct"])},
}

# ---------------------------------------------------------------- residual momentum
from nextgen.residual_momentum import compute_rolling_residual_momentum

rng = np.random.default_rng(7)
T = 1200
bench = pd.Series(rng.normal(0, 0.01, T), index=pd.RangeIndex(T))
a = 1.5 * bench + pd.Series(rng.normal(0, 0.005, T), index=pd.RangeIndex(T))
b = 0.5 * bench + pd.Series(rng.normal(0, 0.005, T), index=pd.RangeIndex(T))
panel = pd.DataFrame({"A": a, "B": b})
res = compute_rolling_residual_momentum(panel, bench, lookback=252, skip_recent=21)

# Independent row-level implementation of the documented formula
def manual_at(row, lookback=252, skip_recent=21, rf=0.065):
    drf = rf / 252.0
    S = panel.to_numpy() - drf
    M = bench.to_numpy() - drf
    eff = lookback - skip_recent
    # recompute eps for every t needed by std and sum windows
    eps = {}
    for t in range(max(0, row - lookback + 1), row + 1):
        lo = max(0, t - lookback + 1)
        if t - lo + 1 < 50:
            eps[t] = None
            continue
        m = M[lo:t+1]
        vb = np.var(m, ddof=1)
        vals = []
        for j in range(S.shape[1]):
            w = S[lo:t+1, j]
            beta = np.cov(w, m, ddof=1)[0, 1] / vb if vb > 1e-8 else 1.0
            alpha = np.mean(w) - beta * np.mean(m)
            vals.append(S[t, j] - (alpha + beta * M[t]))
        eps[t] = np.array(vals)
    window = [eps[t] for t in range(max(0, row - lookback + 1), row + 1) if eps[t] is not None]
    estd = np.clip(np.std(np.vstack(window), axis=0, ddof=1), 1e-4, None)
    hi = row - skip_recent
    lo2 = hi - eff + 1
    if lo2 < 0:
        return np.zeros(S.shape[1])
    sw = np.vstack([eps[t] for t in range(lo2, hi + 1) if eps[t] is not None])
    score = sw.sum(axis=0) / (estd * np.sqrt(eff))
    return np.clip(score, -5.0, 5.0)

sample_rows = [600, 800, 1100]
sample_diffs = []
for rr in sample_rows:
    man = manual_at(rr)
    sample_diffs.append(float(np.max(np.abs(res.to_numpy()[rr] - man))))

diff = float(max(sample_diffs))

spike = panel.copy(); spike.iloc[-3:, 0] += 0.05
res_spike = compute_rolling_residual_momentum(spike, bench, lookback=252, skip_recent=21)

short = compute_rolling_residual_momentum(panel.iloc[:100], bench.iloc[:100])

OUT["residual_momentum"] = {
    "shape": list(res.shape),
    "last_A": round(float(res["A"].iloc[-1]), 4),
    "last_B": round(float(res["B"].iloc[-1]), 4),
    "non_zero_rows_A": int((res["A"].abs() > 1e-9).sum()),
    "sampled_rows": sample_rows,
    "max_abs_diff_vs_manual_rows": round(diff, 10),
    "skip_21_dampens_spike": {
        "without_spike": round(float(res["A"].iloc[-1]), 6),
        "with_5pct_last3": round(float(res_spike["A"].iloc[-1]), 6),
        "delta": round(float(res_spike["A"].iloc[-1] - res["A"].iloc[-1]), 6),
    },
    "short_history_fail_closed_zero": bool((short.to_numpy() == 0).all()),
    "finite": bool(np.isfinite(res.to_numpy()).all()),
    "within_clip": bool((res.abs().to_numpy() <= 5.0).all()),
    "checks": {
        "matches_manual_recalculation": diff < 1e-6,
        "spike_bounded": abs(float(res_spike["A"].iloc[-1] - res["A"].iloc[-1])) < 0.5,
        "short_zero": bool((short.to_numpy() == 0).all()),
        "bounded": bool((res.abs().to_numpy() <= 5.0).all()),
    },
}

# ---------------------------------------------------------------- vol targeting
from nextgen.volatility_targeting import (
    compute_ewma_realized_volatility, compute_volatility_target_scalar,
    compute_dynamic_cash_shield_scalar, scale_position_quantities_by_shield)

const = pd.Series([0.01] * 300)
rvol = float(compute_ewma_realized_volatility(const).iloc[-1])
scalar = float(compute_volatility_target_scalar(const, target_vol=0.12).iloc[-1])
shield_bull = compute_dynamic_cash_shield_scalar(True, 0.24, 0.12, 1.0)
shield_half = compute_dynamic_cash_shield_scalar(True, 0.24, 0.12, 0.25)
shield_bear = compute_dynamic_cash_shield_scalar(False, 0.24, 0.12, 1.0)
scaled = scale_position_quantities_by_shield({"A": 100, "B": 33}, 0.5)

OUT["vol_targeting"] = {
    "ewma_ann_vol_const_1pct": round(rvol, 4),
    "expected_ann_vol": round(0.01 * math.sqrt(252), 4),
    "scalar": round(scalar, 4),
    "expected_scalar": round(min(1.0, max(0.20, 0.12 / (0.01 * math.sqrt(252)))), 4),
    "shield_bull_full_breadth": shield_bull,
    "shield_bull_quarter_breadth": round(shield_half, 4),
    "shield_bear": shield_bear,
    "scaled_quantities": scaled,
    "checks": {
        "vol_match": close(rvol, 0.01 * math.sqrt(252), 1e-3),
        "scalar_match": close(scalar, 0.12 / (0.01 * math.sqrt(252)), 1e-3),
        "bear_zero": shield_bear == 0.0,
        "breadth_sqrt": close(shield_half, 0.25, 1e-6),
        "integer_scaling": scaled == {"A": 50, "B": 16},
    },
}

# ---------------------------------------------------------------- delivery flow
from nextgen.delivery_flow import (
    compute_close_location_value, compute_delivery_absorption_flow,
    compute_smart_money_footprint_index, evaluate_microstructure_buy_gate)

clv = {
    "at_high": compute_close_location_value(110, 110, 90),
    "at_low": compute_close_location_value(90, 110, 90),
    "mid": compute_close_location_value(100, 110, 90),
    "flat": compute_close_location_value(100, 100, 100),
}
daf = compute_delivery_absorption_flow(1_000_000, 100.0, 100.0, 90.0, median_delivery_val_cr=10.0)
smfi = compute_smart_money_footprint_index([1.0, 2.0, 3.0], decay_factor=0.80)
gates = {
    "distribution": evaluate_microstructure_buy_gate(-2.0),
    "accumulation": evaluate_microstructure_buy_gate(3.0),
    "neutral": evaluate_microstructure_buy_gate(0.0),
    "nan": evaluate_microstructure_buy_gate(float("nan")),
}
OUT["delivery_flow"] = {
    "clv": clv,
    "daf": round(daf, 6),
    "smfi": round(smfi, 6),
    "expected_smfi": round(3.0 + 2.0 * 0.8 + 1.0 * 0.8 ** 2, 6),
    "gates": {k: {"allow_buy": v["allow_buy"], "action": v["action"]} for k, v in gates.items()},
    "checks": {
        "clv_high": close(clv["at_high"], 1.0), "clv_low": close(clv["at_low"], -1.0),
        "clv_mid": close(clv["mid"], 0.0), "clv_flat": close(clv["flat"], 0.0),
        "daf": close(daf, 1.0, 1e-6), "smfi": close(smfi, 5.24, 1e-6),
        "veto": gates["distribution"]["allow_buy"] is False,
        "accum": gates["accumulation"]["allow_buy"] is True,
        "nan_veto": gates["nan"]["allow_buy"] is False,
    },
}

# ---------------------------------------------------------------- cache
from cache.fast_cache import FastDataCache

tmp = Path(tempfile.mkdtemp(prefix="mipcache_"))
try:
    cache = FastDataCache(cache_dir=tmp, max_cache_size_mb=1)
    df = pd.DataFrame({"a": np.arange(10), "b": np.linspace(0, 1, 10), "c": list("abcdefghij")})
    key = cache.make_key("unit_test", {"x": 1})
    stored = cache.store(key, df, description="unit test")
    got = cache.get(key)
    equal = got is not None and got.shape == df.shape and np.allclose(got["a"], df["a"]) and list(got["c"]) == list(df["c"])

    k1 = cache.compute_cache_key(ROOT / "data/universe.db", "prices", "2020-01-01", "2026-10-19", ["A", "B"])
    k2 = cache.compute_cache_key(ROOT / "data/universe.db", "prices", "2020-01-01", "2026-10-19", ["A", "B"])
    k3 = cache.compute_cache_key(ROOT / "data/universe.db", "prices", "2020-01-01", "2026-10-19", ["A", "C"])
    stable = k1 == k2 and k1 != k3

    files_before = len(list(tmp.glob("*.npz"))) + len(list(tmp.glob("*.feather")))
    for n in range(4):
        big = pd.DataFrame(np.random.default_rng(n).random((60000, 4)), columns=list("abcd"))
        cache.store(cache.make_key(f"evict_{n}"), big)
    size_mb = sum(f.stat().st_size for f in tmp.iterdir() if f.is_file()) / (1024 * 1024)
    entries = len(json.loads((tmp / "cache_manifest.json").read_text()))
    cleared = cache.clear()
    OUT["cache"] = {
        "store_ok": bool(stored),
        "roundtrip_equal": bool(equal),
        "format": "npz (pyarrow absent)",
        "key_stable_for_same_query": bool(stable),
        "files_after_first_store": files_before,
        "after_eviction": {"manifest_entries": entries, "disk_mb": round(size_mb, 2), "limit_mb": 1.0},
        "clear_deleted": cleared,
        "manifest_empty_after_clear": json.loads((tmp / "cache_manifest.json").read_text()) == {},
        "limit_exceeded_by_single_entry": size_mb > 1.0,
    }
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---------------------------------------------------------------- cloud sync gzip
from scripts.cloud_sync import compress_file, decompress_file

tmp2 = Path(tempfile.mkdtemp(prefix="mipsync_"))
try:
    src = tmp2 / "blob.bin"
    data = np.random.default_rng(11).bytes(2 * 1024 * 1024)
    src.write_bytes(data)
    gz = tmp2 / "blob.bin.gz"
    out = tmp2 / "blob.out"
    orig_b, gz_b = compress_file(src, gz, compresslevel=6)
    _, dec_b = decompress_file(gz, out)
    OUT["cloud_sync"] = {
        "original_bytes": orig_b, "compressed_bytes": gz_b,
        "decompressed_bytes": dec_b,
        "ratio_pct_saved": round((1 - gz_b / orig_b) * 100, 2),
        "hash_match": hashlib.sha256(data).hexdigest() == hashlib.sha256(out.read_bytes()).hexdigest(),
    }
finally:
    shutil.rmtree(tmp2, ignore_errors=True)

print(json.dumps(OUT, indent=2, default=str))
Path("/tmp/mip_modules_evidence.json").write_text(json.dumps(OUT, indent=2, default=str))
