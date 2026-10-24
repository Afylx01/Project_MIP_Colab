import sys, json, math
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats as st

ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
sys.path.insert(0, str(ROOT))
from brute_force.runner import BruteForceCampaignRunner
from brute_force.grid import (FILTER_RETRACE, FILTER_TREND, FILTER_RS,
                              FILTER_REGIME, FILTER_SECTOR_CAP, FILTER_VOL_TARGETING,
                              LOOKBACK_VALUES, EMA_SPAN_VALUES)
from nextgen.risk_statistics import compute_deflated_sharpe_ratio, compute_probabilistic_sharpe_ratio

OUT = ROOT / "reports" / "analysis_evidence"
RF = 0.065
CANDIDATES = {
    "L1_A_voltarget": dict(lookback=315, ema=250, top_n=20, buffer=30, cap=2, sizing="equal_weight", vol_target=True),
    "L2_A_voltarget_ema150": dict(lookback=315, ema=150, top_n=20, buffer=30, cap=2, sizing="equal_weight", vol_target=True),
    "L3_dd30_max_cagr": dict(lookback=315, ema=200, top_n=25, buffer=30, cap=3, sizing="equal_weight", vol_target=False),
    "L4_A_base": dict(lookback=315, ema=250, top_n=20, buffer=30, cap=2, sizing="equal_weight", vol_target=False),
    "L5_min_oos_dd": dict(lookback=252, ema=200, top_n=25, buffer=20, cap=1, sizing="equal_weight", vol_target=False),
    "L6_dd30_vt": dict(lookback=315, ema=200, top_n=25, buffer=30, cap=3, sizing="equal_weight", vol_target=True),
}

runner = BruteForceCampaignRunner(base_dir=ROOT)
cube = runner.ensure_cube(universe_name="NIFTY500", benchmark="NIFTY500")

def flags(c):
    f = FILTER_RETRACE | FILTER_TREND | FILTER_RS | FILTER_REGIME
    if c["cap"] < 90: f |= FILTER_SECTOR_CAP
    if c.get("vol_target"): f |= FILTER_VOL_TARGETING
    return f

def idx_for(start, end):
    s = min(cube.date_to_idx[d] for d in cube.dates if d >= start)
    e = max(cube.date_to_idx[d] for d in cube.dates if d <= end)
    return s, e

def param(c, s, e, friction=15.0, slippage=5.0):
    return {"param_id":0,"schedule_idx":1,"start_date_idx":s,"end_date_idx":e,
            "lookback_idx":LOOKBACK_VALUES.index(c["lookback"]),"ema_idx":EMA_SPAN_VALUES.index(c["ema"]),
            "top_n":c["top_n"],"exit_buffer_rank":c["buffer"],"max_per_sector":c["cap"],
            "sizing_mode":c["sizing"],"filter_flags":flags(c),
            "retrace_threshold":0.8,"initial_capital":1_000_000.0,
            "friction_bps":friction,"slippage_bps":slippage,"risk_per_trade_pct":1.0}

def exact_curve(c, start, end, friction=15.0, slippage=5.0):
    s, e = idx_for(start, end)
    off=int(cube.schedule_offsets[1]); ln=int(cube.schedule_lengths[1])
    idx=[int(i) for i in cube.rebalance_indices[off:off+ln] if s<=i<=e]
    p=param(c,s,e,friction,slippage)
    dates=[]; eq=[]
    for i in idx:
        j=min(i+1,e)
        q=dict(p); q["end_date_idx"]=j
        eq.append(float(runner.engine.execute_sweep([q],cube,num_threads=1)[0]["ending_equity"]))
        dates.append(cube.dates[j])
    return dates, np.array(eq)

def metrics(eq, dates, start, end):
    mask=np.array([(d>=start and d<=end) for d in dates]); idx=np.where(mask)[0]
    if len(idx)<2: return None
    if idx[0]>0: idx=np.concatenate([[idx[0]-1],idx])
    e=eq[idx]; rets=np.diff(e)/e[:-1]; n=len(rets); years=n/12
    cagr=(e[-1]/e[0])**(1/years)-1
    vol=rets.std(ddof=1)*math.sqrt(12)
    sharpe=(rets.mean()*12-RF)/vol if vol>0 else 0
    down=rets[rets<RF/12]-RF/12
    dstd=down.std(ddof=1)*math.sqrt(12) if len(down)>1 else vol
    sortino=(rets.mean()*12-RF)/dstd if dstd>0 else 0
    peak=np.maximum.accumulate(e); dd=(e-peak)/peak
    mdd=dd.min()
    return {"months":n,"cagr_pct":round(cagr*100,2),"vol_pct":round(vol*100,2),
            "sharpe":round(sharpe,2),"sortino":round(sortino,2),
            "maxdd_monthly_pct":round(mdd*100,2),
            "calmar":round(cagr/abs(mdd),2) if mdd<0 else 0,
            "win_rate_pct":round(float((rets>0).mean()*100),1),
            "worst_month_pct":round(float(rets.min()*100),2)}, rets

out={"generated":pd.Timestamp.utcnow().isoformat(),"candidates":{}}
for name,c in CANDIDATES.items():
    d16,eq16=exact_curve(c,"2018-01-01","2026-08-31")
    full,r=metrics(eq16,d16,"2018-01-01","2026-08-31")
    is_,_=metrics(eq16,d16,"2018-01-01","2021-12-31")
    oos,_=metrics(eq16,d16,"2022-01-01","2026-08-31")
    d40,eq40=exact_curve(c,"2018-01-01","2026-08-31",30.0,10.0)
    cost,_=metrics(eq40,d40,"2018-01-01","2026-08-31")
    # engine summary (daily DD, trades)
    s,e=idx_for("2018-01-01","2026-08-31")
    p=param(c,s,e)
    arr=runner.engine.execute_sweep([p],cube,num_threads=1)[0]
    # statistics
    n=len(r); excess=r-RF/12
    def safe(v): return None if v is None else round(float(v),4)
    stats={
        "psr":safe(compute_probabilistic_sharpe_ratio(excess,benchmark_sr=0.0,annualization_factor=12)),
        "dsr_k5":safe(compute_deflated_sharpe_ratio(excess,n_trials=5,annualization_factor=12)),
        "dsr_k8000":safe(compute_deflated_sharpe_ratio(excess,n_trials=8000,annualization_factor=12)),
        "t_vs_zero":round(float(st.ttest_1samp(r,0,alternative="greater").statistic),2),
        "p_vs_zero":round(float(st.ttest_1samp(r,0,alternative="greater").pvalue),6),
    }
    out["candidates"][name]={"settings":c,"full":full,"is":is_,"oos":oos,"cost_40bps":cost,
        "engine":{"cagr_pct":float(arr["cagr"]),"sharpe":float(arr["sharpe"]),
                  "daily_maxdd_pct":float(arr["max_drawdown"]),"trades":int(arr["total_trades"]),
                  "calmar":float(arr["calmar"])},
        "statistics":stats}
    print(name, "full", full, "| OOS", oos, "| dailyDD", round(float(arr["max_drawdown"]),2))

# benchmark
s,e=idx_for("2018-01-01","2026-08-31")
b=[]; off=int(cube.schedule_offsets[1]); ln=int(cube.schedule_lengths[1])
bidx=[int(x) for x in cube.rebalance_indices[off:off+ln] if s<=int(x)<=e]
for i in bidx: b.append(float(cube.bench_closes[i]))
bd=[cube.dates[i] for i in bidx]
bm,bret=metrics(np.array(b),bd,"2018-01-01","2026-08-31")
out["benchmark"]=bm
(OUT/"30_low_dd_validation.json").write_text(json.dumps(out,indent=2,default=str))
print(json.dumps(out,indent=2,default=str)[:2500])
