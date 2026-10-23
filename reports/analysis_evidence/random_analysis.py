import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
sys.path.insert(0, str(ROOT))
from brute_force.runner import BruteForceCampaignRunner

OUT = ROOT / "reports" / "analysis_evidence"
RF = 0.065
W = dict(lookback=315, ema_trend=250, top_n=20, exit_buffer_rank=30,
         max_per_sector=2, sizing_mode="equal_weight")
RNG = np.random.default_rng(20261023)

t0 = time.time()
runner = BruteForceCampaignRunner(base_dir=ROOT)
cube = runner.ensure_cube(universe_name="NIFTY500", benchmark="NIFTY500")
print("cube", round(time.time()-t0,1))

def idx_for(start, end):
    s = min(cube.date_to_idx[d] for d in cube.dates if d >= start)
    e = max(cube.date_to_idx[d] for d in cube.dates if d <= end)
    return s, e

def bench_cagr(start, end):
    s, e = idx_for(start, end)
    b0, b1 = float(cube.bench_closes[s]), float(cube.bench_closes[e])
    years = (pd.Timestamp(cube.dates[e]) - pd.Timestamp(cube.dates[s])).days / 365.25
    return ((b1/b0)**(1/max(years,1e-9))-1)*100 if b0>0 and b1>0 else 0.0

def run_window(start, end):
    res = runner.run_custom_backtest(start_date=start, end_date=end, universe_name="NIFTY500",
        benchmark="NIFTY500", schedule="monthly", **W)
    return res

# 200 random windows: 2-5 calendar years, start 2008-01 .. 2024-08
starts = pd.date_range("2008-01-01","2024-08-01",freq="MS")
rows=[]
for _ in range(200):
    st = starts[int(RNG.integers(0,len(starts)))]
    yrs = int(RNG.integers(2,6))
    en = min(st + pd.DateOffset(years=yrs), pd.Timestamp("2026-08-31"))
    if en <= st: continue
    res = run_window(str(st.date()), str(en.date()))
    bc = bench_cagr(str(st.date()), str(en.date()))
    rows.append({"start":str(st.date()),"end":str(en.date()),
                 "years":round((en-st).days/365.25,2),
                 "cagr":float(res["cagr_pct"]),"sharpe":float(res["sharpe_ratio"]),
                 "maxdd":float(res["max_drawdown_pct"]),"calmar":float(res["calmar_ratio"]),
                 "trades":int(res["total_trades"]),"bench_cagr":bc,
                 "excess":float(res["cagr_pct"])-bc})
d=pd.DataFrame(rows)
d.to_csv(OUT/"24_random_windows.csv", index=False)

def summ(x):
    x=np.asarray(x,dtype=float)
    return {"n":int(len(x)),"median":round(float(np.median(x)),2),
            "mean":round(float(x.mean()),2),
            "p05":round(float(np.percentile(x,5)),2),"p95":round(float(np.percentile(x,95)),2),
            "min":round(float(x.min()),2),"max":round(float(x.max()),2),
            "pct_positive":round(float((x>0).mean()*100),1)}

def block(df):
    return {"n":len(df),"cagr":summ(df.cagr),"sharpe":summ(df.sharpe),
            "maxdd":summ(df.maxdd),"excess":summ(df.excess),
            "pct_beat_benchmark":round(float((df.excess>0).mean()*100),1),
            "pct_dd_under_20":round(float((df.maxdd>-20).mean()*100),1),
            "pct_dd_under_25":round(float((df.maxdd>-25).mean()*100),1),
            "pct_sharpe_over_1":round(float((df.sharpe>1).mean()*100),1)}

modern = d[d.start>="2016-01-01"]
modern_clean = modern[(modern.cagr>-80)&(modern.cagr<150)&(modern.trades>=20)]
all_clean = d[(d.cagr>-80)&(d.cagr<150)&(d.trades>=20)]
out={"generated":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
     "recommended":W,"R1_random_windows":{
         "all":block(d),"all_clean":block(all_clean),
         "modern_2016_plus":block(modern),"modern_clean":block(modern_clean),
         "duration_years":summ(d.years)}}

# R2 from saved grid
m2=pd.read_csv(OUT/"25_random_perturbations.csv")
out["R2_random_perturbations"]={
 "n":len(m2),"is_cagr":summ(m2.is_cagr),"is_sharpe":summ(m2.is_sharpe),
 "oos_cagr":summ(m2.oos_cagr),"oos_sharpe":summ(m2.oos_sharpe),"oos_dd":summ(m2.oos_dd),
 "pct_oos_positive":round(float((m2.oos_cagr>0).mean()*100),1),
 "pct_oos_beat_bench":round(float((m2.oos_cagr>10.37).mean()*100),1),
 "corr_is_oos_cagr":round(float(m2.is_cagr.corr(m2.oos_cagr)),3),
 "corr_is_oos_sharpe":round(float(m2.is_sharpe.corr(m2.oos_sharpe)),3)}

# R3 from saved grid
m3=pd.read_csv(OUT/"26_random_costs.csv")
out["R3_random_costs"]={
 "n":len(m3),"cagr":summ(m3.cagr),"sharpe":summ(m3.sharpe),"maxdd":summ(m3.maxdd),
 "pct_cagr_over_20":round(float((m3.cagr>20).mean()*100),1),
 "pct_sharpe_over_0_9":round(float((m3.sharpe>0.9).mean()*100),1),
 "worst":m3.sort_values("cagr").iloc[0].to_dict(),
 "best":m3.sort_values("cagr").iloc[-1].to_dict()}

# R6 from monthly CSV
m6=pd.read_csv(OUT/"27_monthly_returns.csv")
r=m6.strategy_ret.to_numpy(); br=m6.bench_ret.to_numpy()
up,dn=br>=0,br<0
roll=pd.Series(r).rolling(12).apply(lambda x: np.prod(1+x)-1,raw=True).dropna()
out["R6_regimes"]={
 "n_months":len(r),"bench_up_months":int(up.sum()),"bench_down_months":int(dn.sum()),
 "strategy_mean_up_pct":round(float(r[up].mean()*100),2),
 "strategy_mean_down_pct":round(float(r[dn].mean()*100),2),
 "win_rate_up_pct":round(float((r[up]>0).mean()*100),1),
 "win_rate_down_pct":round(float((r[dn]>0).mean()*100),1),
 "rolling_12m":summ(roll*100),
 "rolling_12m_pct_positive":round(float((roll>0).mean()*100),1),
 "corr_vs_bench":round(float(np.corrcoef(r,br)[0,1]),3)}

# R7 low DD from saved grid (C max_drawdown is negative in run_sweep)
m7=pd.read_csv(OUT/"28_low_dd_grid.csv")
def pickr(df,score):
    if df.empty: return None
    df=df.copy(); df["score"]=score(df)
    r=df.sort_values("score",ascending=False).iloc[0]
    return {k:(bool(r[k]) if isinstance(r[k],(bool,np.bool_)) else (float(r[k]) if isinstance(r[k],(float,np.floating)) else int(r[k]) if isinstance(r[k],(int,np.integer)) else r[k]))
            for k in ("lookback","ema","top_n","buffer","cap","sizing","vol_target",
                      "is_cagr","is_sharpe","is_dd","is_calmar","oos_cagr","oos_sharpe","oos_dd","oos_calmar")}
fams={}
for name,cond in {
 "dd20_max_cagr":(m7.is_dd>-20)&(m7.oos_dd>-20),
 "dd22_max_cagr":(m7.is_dd>-22)&(m7.oos_dd>-22),
 "dd25_max_cagr":(m7.is_dd>-25)&(m7.oos_dd>-25),
 "dd20_max_calmar":(m7.is_dd>-20)&(m7.oos_dd>-20),
}.items():
    sub=m7[cond&(m7.is_cagr>20)&(m7.oos_cagr>15)&(m7.is_trades>100)&(m7.oos_trades>50)]
    fams[name]=pickr(sub,(lambda x:x.oos_cagr) if name.endswith("cagr") else (lambda x:x.oos_cagr/x.oos_dd.abs().clip(lower=1e-6)))
out["R7_low_dd_search"]={"grid":len(m7),"families":fams}
(OUT/"29_random_robustness.json").write_text(json.dumps(out,indent=2,default=str))
print(json.dumps(out,indent=2,default=str))
