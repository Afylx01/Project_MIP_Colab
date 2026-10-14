"""
Project MIP Pydroid 3: NSE Delivery Volume & Accumulation/Distribution Manager
Directive: DIR-PROD-PYDROID3-PARITY-01 (MIP-1 v5.5.1 Parity)

Fetches official NSE daily delivery metrics from sec_bhavdata_full.csv.
Computes:
  - Delivery % (Delivery Qty / Total Traded Qty * 100)
  - 5-Day Prior Delivery Average & Delivery Times multiplier (Today / 5D Avg)
  - Institutional Accumulation vs. Distribution Classifier:
      🟢 ACCUMULATION : Price >= 0.0% AND (Delivery % >= 45% OR Delivery Times >= 1.5x)
      🔴 DISTRIBUTION : Price <= -1.0% AND (Delivery % >= 50% OR Delivery Times >= 1.5x)
      ⚪ NEUTRAL      : All other conditions
"""

import os
import io
import datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from .data_engine import get_base_dir

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.nseindia.com/",
    "Accept": "*/*",
}


class NSEDeliveryManager:
    """Manages NSE daily delivery metrics and accumulation/distribution classification."""

    BASE_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d_str}.csv"

    def __init__(self, cache_dir: Optional[Path] = None):
        base = get_base_dir()
        self.cache_dir = Path(cache_dir) if cache_dir else base / "data" / "bhavcopy_delivery"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, pd.DataFrame] = {}

    def _get_session(self):
        try:
            from curl_cffi import requests as cffi_requests
            return cffi_requests.Session(impersonate="chrome")
        except ImportError:
            import requests
            return requests.Session()

    def _fetch_single_day(self, date_obj: datetime.date) -> Optional[pd.DataFrame]:
        """Fetches sec_bhavdata_full CSV for a specific trading session."""
        d_str = date_obj.strftime("%d%m%Y")
        local_file = self.cache_dir / f"sec_bhavdata_{date_obj.strftime('%Y%m%d')}.csv"
        
        # Check local cache
        if local_file.exists() and local_file.stat().st_size > 1000:
            try:
                return pd.read_csv(local_file, on_bad_lines="skip")
            except Exception as e:
                print(f"[DeliveryManager] Warning: Failed to parse cache file {local_file.name}: {e}")

        url = self.BASE_URL.format(d_str=d_str)
        session = self._get_session()
        try:
            resp = session.get(url, headers=HEADERS, timeout=12)
            if resp.status_code == 200 and len(resp.content) > 1000:
                local_file.write_bytes(resp.content)
                return pd.read_csv(local_file, on_bad_lines="skip")
        except Exception as e:
            print(f"[DeliveryManager] Info: Delivery bhavdata for {d_str} unavailable ({e})")

        return None

    def get_delivery_data(self, date_obj: datetime.date) -> pd.DataFrame:
        """Returns clean DataFrame of delivery metrics with 5-day delivery times & action."""
        if not isinstance(date_obj, datetime.date):
            if isinstance(date_obj, str):
                date_obj = datetime.datetime.strptime(date_obj, "%Y-%m-%d").date()
            else:
                return pd.DataFrame()

        std_date = date_obj.strftime("%Y-%m-%d")
        if std_date in self._cache:
            return self._cache[std_date]

        df = self._fetch_single_day(date_obj)
        if df is None or df.empty:
            return pd.DataFrame()

        try:
            VALID_SERIES = {"EQ", "BE", "BZ", "SM"}
            df.columns = [c.strip().upper() for c in df.columns]
            if "SERIES" in df.columns:
                df = df[df["SERIES"].astype(str).str.strip().isin(VALID_SERIES)].copy()
            else:
                return pd.DataFrame()

            clean_df = pd.DataFrame()
            clean_df["symbol"] = df["SYMBOL"].astype(str).str.strip()
            clean_df["series"] = df["SERIES"].astype(str).str.strip()

            for col in ["CLOSE_PRICE", "PREV_CLOSE", "DELIV_QTY", "DELIV_PER", "TTL_TRD_QNTY", "TURNOVER_LACS"]:
                if col in df.columns:
                    s = df[col].astype(str).str.replace(",", "", regex=False).str.strip()
                    clean_df[col.lower()] = pd.to_numeric(s, errors="coerce")
                else:
                    clean_df[col.lower()] = np.nan

            # For trade-to-trade / surveillance series (BE, BZ, SM), delivery is 100% compulsory
            is_be = clean_df["series"].isin(["BE", "BZ", "SM"])
            clean_df.loc[is_be & clean_df["deliv_qty"].isna(), "deliv_qty"] = clean_df.loc[is_be & clean_df["deliv_qty"].isna(), "ttl_trd_qnty"]
            clean_df.loc[is_be & clean_df["deliv_per"].isna(), "deliv_per"] = 100.0

            clean_df["delivery_value_cr"] = ((clean_df["deliv_qty"] * clean_df["close_price"]) / 1e7).round(2)
            clean_df["deliv_ret_pct"] = (((clean_df["close_price"] / clean_df["prev_close"]) - 1.0) * 100).round(2)
            clean_df = clean_df.drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)

            # Compute 5-Day Prior Delivery Average and Delivery Times
            prior_dfs = []
            d_prior = date_obj - datetime.timedelta(days=1)
            while len(prior_dfs) < 5 and (date_obj - d_prior).days <= 14:
                if d_prior.weekday() < 5:
                    p_df = self._fetch_single_day(d_prior)
                    if p_df is not None and not p_df.empty:
                        p_df.columns = [c.strip().upper() for c in p_df.columns]
                        if "SERIES" in p_df.columns:
                            p_df = p_df[p_df["SERIES"].astype(str).str.strip().isin(VALID_SERIES)]
                        if "DELIV_QTY" in p_df.columns and "SYMBOL" in p_df.columns:
                            s_qty = pd.to_numeric(p_df["DELIV_QTY"].astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")
                            if "TTL_TRD_QNTY" in p_df.columns and "SERIES" in p_df.columns:
                                is_p_be = p_df["SERIES"].astype(str).str.strip().isin(["BE", "BZ", "SM"])
                                t_qty = pd.to_numeric(p_df["TTL_TRD_QNTY"].astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")
                                s_qty = s_qty.fillna(t_qty.where(is_p_be))
                            prior_dfs.append(pd.DataFrame({"symbol": p_df["SYMBOL"].astype(str).str.strip(), "deliv_qty": s_qty}))
                d_prior -= datetime.timedelta(days=1)

            if prior_dfs:
                concat_prior = pd.concat(prior_dfs, ignore_index=True)
                avg_5d = concat_prior.groupby("symbol")["deliv_qty"].mean().to_dict()
                clean_df["deliv_5d_avg"] = clean_df["symbol"].map(avg_5d).round(0)
                clean_df["deliv_times"] = (clean_df["deliv_qty"] / clean_df["deliv_5d_avg"]).round(1)
            else:
                clean_df["deliv_5d_avg"] = np.nan
                clean_df["deliv_times"] = np.nan

            # Institutional Accumulation vs Distribution Classifier
            is_acc = (clean_df["deliv_ret_pct"].fillna(0.0) >= 0.0) & (
                (clean_df["deliv_per"].fillna(0.0) >= 45.0) | (clean_df["deliv_times"].fillna(0.0) >= 1.5)
            )
            is_dist = (clean_df["deliv_ret_pct"].fillna(0.0) <= -1.0) & (
                (clean_df["deliv_per"].fillna(0.0) >= 50.0) | (clean_df["deliv_times"].fillna(0.0) >= 1.5)
            )
            clean_df["deliv_action"] = "⚪ NEUTRAL"
            clean_df.loc[is_acc, "deliv_action"] = "🟢 ACCUMULATION"
            clean_df.loc[is_dist, "deliv_action"] = "🔴 DISTRIBUTION"

            self._cache[std_date] = clean_df
            return clean_df

        except Exception as e:
            return pd.DataFrame()
