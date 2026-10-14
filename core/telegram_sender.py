"""
Project MIP Pydroid 3: Pure-Python Telegram Bot Dispatcher
Directive: DIR-PROD-PYDROID3-PARITY-01 (MIP-1 v5.5.1 Reporting Style)

Pure Python REST client for Telegram Bot API:
  - Dispatches formatted HTML/Markdown alerts.
  - Sends high-resolution PNG charts (sendPhoto) and 12-sheet Excel workbooks (sendDocument).
  - Includes TradingView hyperlinks, delivery accumulation tags, and Momentify ETF picks.
  - Zero external binary dependency (/usr/local/bin/telegram-notify not needed).
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd

from .data_engine import get_base_dir


def load_env_credentials() -> Dict[str, str]:
    """Reads credentials from .env file or system environment."""
    base_dir = get_base_dir()
    env_file = base_dir / ".env"
    creds = {
        "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
    }

    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k == "TELEGRAM_BOT_TOKEN" and not creds["bot_token"]:
                        creds["bot_token"] = v
                    elif k == "TELEGRAM_CHAT_ID" and not creds["chat_id"]:
                        creds["chat_id"] = v

    return creds


class PydroidTelegramSender:
    """Dispatches Telegram notifications and deliverables natively inside Pydroid 3."""

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        creds = load_env_credentials()
        self.bot_token = bot_token or creds.get("bot_token", "")
        self.chat_id = chat_id or creds.get("chat_id", "")
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def _get_session(self):
        """Attempts to return curl_cffi Chrome-impersonated session, else requests session."""
        try:
            from curl_cffi import requests as cffi_requests
            return cffi_requests.Session(impersonate="chrome")
        except ImportError:
            try:
                import requests
                return requests.Session()
            except ImportError:
                return None

    def send_message(self, text: str, parse_mode: str = "HTML", dry_run: bool = False) -> bool:
        """Sends an HTML/text message to the designated Telegram chat."""
        if dry_run:
            print("[Telegram] DRY RUN — Message content:")
            print("-" * 50)
            print(text)
            print("-" * 50)
            return True

        if not self.is_configured():
            print("⚠ Telegram credentials missing! Please configure .env with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
            return False

        session = self._get_session()
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        url = f"{self.api_url}/sendMessage"
        try:
            if session:
                resp = session.post(url, json=payload, timeout=15)
                res_data = resp.json()
            else:
                import urllib.request
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=15) as r:
                    res_data = json.loads(r.read().decode("utf-8"))

            if res_data.get("ok"):
                msg_id = res_data.get('result', {}).get('message_id')
                print(f"✓ Telegram message sent successfully (Msg ID: {msg_id})")
                return True
            else:
                print(f"✗ Telegram API Error: {res_data.get('description')}")
                return False
        except Exception as e:
            print(f"✗ Telegram request error: {e}")
            return False

    def send_photo(self, photo_path: Path, caption: Optional[str] = None, dry_run: bool = False) -> bool:
        """Uploads and dispatches a PNG chart or image."""
        photo_path = Path(photo_path)
        if dry_run:
            print(f"[Telegram] DRY RUN — Would dispatch photo: {photo_path} (Caption: {caption})")
            return True

        if not self.is_configured() or not photo_path.exists():
            return False

        url = f"{self.api_url}/sendPhoto"
        try:
            import requests
            with open(photo_path, "rb") as f:
                data = {"chat_id": self.chat_id}
                if caption:
                    data["caption"] = caption
                    data["parse_mode"] = "HTML"
                files = {"photo": (photo_path.name, f)}
                resp = requests.post(url, data=data, files=files, timeout=25)
                res_data = resp.json()

            if res_data.get("ok"):
                print(f"✓ Telegram photo sent: {photo_path.name}")
                return True
            else:
                print(f"✗ Telegram photo API Error: {res_data.get('description')}")
                return False
        except Exception as e:
            print(f"✗ Telegram photo transmission failed: {e}")
            return False

    def send_document(self, doc_path: Path, caption: Optional[str] = None, dry_run: bool = False) -> bool:
        """Uploads and dispatches an Excel workbook or HTML tearsheet."""
        doc_path = Path(doc_path)
        if dry_run:
            print(f"[Telegram] DRY RUN — Would dispatch document: {doc_path} (Caption: {caption})")
            return True

        if not self.is_configured() or not doc_path.exists():
            return False

        url = f"{self.api_url}/sendDocument"
        try:
            import requests
            with open(doc_path, "rb") as f:
                data = {"chat_id": self.chat_id}
                if caption:
                    data["caption"] = caption
                    data["parse_mode"] = "HTML"
                files = {"document": (doc_path.name, f)}
                resp = requests.post(url, data=data, files=files, timeout=45)
                res_data = resp.json()

            if res_data.get("ok"):
                print(f"✓ Telegram document sent: {doc_path.name}")
                return True
            else:
                print(f"✗ Telegram document API Error: {res_data.get('description')}")
                return False
        except Exception as e:
            print(f"✗ Telegram document transmission failed: {e}")
            return False


def format_telegram_alert(
    top_df: pd.DataFrame,
    breadth: Dict,
    sectors: Dict,
    regime: Dict,
    as_of_date: str,
    top_etf_df: Optional[pd.DataFrame] = None,
    delivery_df: Optional[pd.DataFrame] = None,
    universe_label: str = "NIFTY 500",
) -> str:
    """Formats institutional Telegram HTML message with v5.5.1 rich sections."""
    tp = breadth.get("trend_participation", {})
    hp = breadth.get("high_proximity", {})
    nhl = breadth.get("net_highs_lows", {})
    b_reg = breadth.get("regime", {})

    dmap = {}
    if delivery_df is not None and not delivery_df.empty:
        dmap = delivery_df.set_index("symbol").to_dict(orient="index")

    msg = f"🚀 <b>MIP-1 MOMENTUM SCANNER v5.5.1</b>\n"
    msg += f"📅 <b>Date:</b> <code>{as_of_date}</code> | <b>Universe:</b> <code>{universe_label}</code>\n"
    msg += f"🛡️ <b>Benchmark Regime:</b> {regime.get('label', 'N/A')}\n"
    msg += f"📊 <b>Market Breadth:</b> {b_reg.get('label', 'N/A')}\n\n"

    # Breadth Metrics
    msg += f"📈 <b>BREADTH & TREND PARTICIPATION</b>\n"
    msg += f"• <b>> 200 EMA:</b> {tp.get('pct_above_200_ema', 0.0):.1f}% ({tp.get('count_above_200_ema', 0)}/{breadth.get('universe_size', 0)})\n"
    msg += f"• <b>> 50 EMA:</b> {tp.get('pct_above_50_ema', 0.0):.1f}% | <b>> 20 EMA:</b> {tp.get('pct_above_20_ema', 0.0):.1f}%\n"
    msg += f"• <b>Near 52w High:</b> {hp.get('pct_within_20pct_52wh', 0.0):.1f}% (Within 20%)\n"
    msg += f"• <b>52w Net Highs:</b> +{nhl.get('new_52w_highs', 0)} / -{nhl.get('new_52w_lows', 0)} (Net: {nhl.get('net_highs_lows', 0):+d})\n\n"

    # Top Sector Rotation
    msg += f"🔄 <b>TOP MOMENTUM SECTORS</b>\n<pre>"
    msg += f"{'Rank':<4}{'Sector':<11}{'1M Ret':<8}{'Alpha':<8}{'Breadth'}\n"
    msg += "-" * 38 + "\n"
    for s in sectors.get("sectors", [])[:4]:
        msg += f"{s['rank']:<4}{s['sector']:<11}{s['ret_1m']:+5.1f}%  {s['alpha_1m']:+5.1f}%  {s['breadth_200_pct']:4.0f}%\n"
    msg += "</pre>\n"

    # Top 10 Stocks with TradingView hyperlinks and delivery tags
    msg += f"🏆 <b>TOP MOMENTUM STOCKS (Volar Ranking)</b>\n"
    for idx, (_, r) in enumerate(top_df.head(10).iterrows(), 1):
        sym = r["symbol"]
        px = float(r.get("close", 0.0))
        volar = float(r.get("volar_score", 0.0))
        ret_val = float(r.get("ret_1y", 0.0) or r.get("return_252d", 0.0))
        ret_1y = ret_val if abs(ret_val) > 5.0 or ret_val == 0.0 else ret_val * 100.0
        tv_url = f"https://in.tradingview.com/chart/?symbol=NSE:{sym}"

        d_info = dmap.get(sym, {})
        d_per = d_info.get("deliv_per")
        d_times = d_info.get("deliv_times")
        d_str = ""
        if d_per is not None and pd.notna(d_per):
            d_str = f" | Deliv: <code>{d_per:.0f}%</code>"
            if d_times is not None and pd.notna(d_times) and d_times >= 1.5:
                d_str += f" (<b>{d_times:.1f}x</b>)"

        msg += f"<code>{idx:02d}.</code> <a href=\"{tv_url}\"><b>{sym}</b></a> — ₹{px:,.1f} | Volar: <code>{volar:.2f}</code> | 1Y: <code>{ret_1y:+.1f}%</code>{d_str}\n"

    # Top 5 Momentify ALL-ONE ETFs
    if top_etf_df is not None and not top_etf_df.empty:
        msg += f"\n🎯 <b>MOMENTIFY ETF PICKS (ALL-ONE Non-Repeating)</b>\n"
        for idx, (_, r) in enumerate(top_etf_df.head(5).iterrows(), 1):
            sym = r["symbol"]
            und = str(r.get("underlying", ""))[:32]
            px = float(r.get("price", 0.0))
            volar = float(r.get("volar_score", 0.0))
            tv_url = f"https://in.tradingview.com/chart/?symbol=NSE:{sym}"
            msg += f"<code>{idx:02d}.</code> <a href=\"{tv_url}\"><b>{sym}</b></a> — ₹{px:,.1f} | Volar: <code>{volar:.2f}</code> ({und})\n"

    # Institutional Delivery Spikes (₹5Cr+)
    if delivery_df is not None and not delivery_df.empty:
        spikes = delivery_df[delivery_df["delivery_value_cr"].fillna(0) >= 5.0].sort_values("deliv_per", ascending=False).head(3)
        if not spikes.empty:
            msg += f"\n📦 <b>TOP INSTITUTIONAL DELIVERY SPIKES (₹5Cr+)</b>\n"
            for _, r in spikes.iterrows():
                sym = r["symbol"]
                d_per = r.get("deliv_per", 0.0)
                d_val = r.get("delivery_value_cr", 0.0)
                act = r.get("deliv_action", "")
                d_times = r.get("deliv_times")
                t_str = f" ({d_times:.1f}x)" if pd.notna(d_times) else ""
                msg += f"• <b>{sym}</b> {act}: <code>{d_per:.0f}%</code>{t_str} | ₹{d_val:.1f}Cr\n"

    msg += f"\n<i>Generated natively on Samsung Galaxy S23 via Pydroid 3</i>"
    return msg
