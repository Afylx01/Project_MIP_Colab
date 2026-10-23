"""
Project MIP Pydroid 3: Pure-Python Telegram Bot Dispatcher
Directive: DIR-PROD-PYDROID3-PARITY-01 (MIP-1 v5.5.1 Reporting Style)

Pure Python REST client for Telegram Bot API:
  - Dispatches formatted HTML/Markdown alerts.
  - Sends high-resolution PNG charts (sendPhoto) and 12-sheet Excel workbooks (sendDocument).
  - Includes TradingView hyperlinks, delivery accumulation tags, and Momentify ETF picks.
  - Zero external binary dependency (/usr/local/bin/telegram-notify not needed).
"""

from __future__ import annotations
import os
import sys
import json
import html
from pathlib import Path
from typing import Dict, List, Optional, Any
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
    if not creds["bot_token"] or not creds["chat_id"]:
        try:
            from google.colab import userdata
            if not creds["bot_token"]:
                creds["bot_token"] = str(userdata.get("TELEGRAM_BOT_TOKEN") or "")
            if not creds["chat_id"]:
                creds["chat_id"] = str(userdata.get("TELEGRAM_CHAT_ID") or "")
        except Exception:
            pass

    return creds

def _chunk_message(text: str, max_length: int = 4000) -> List[str]:
    """
    Splits a message into Telegram-safe chunks.

    - Never emits a chunk longer than max_length, including single long lines
      and <pre> blocks (hard-split at character boundaries).
    - Preserves the original text exactly when no HTML <pre> tags are present.
    - Closes and reopens <pre> across chunk boundaries.
    """
    if max_length <= 0:
        raise ValueError("max_length must be positive")
    if len(text) <= max_length:
        return [text]

    # Reserve room for a possible "</pre>" suffix and "<pre>" prefix.
    reserve = 14
    atom_limit = max_length - reserve

    # 1. Split into atomic pieces that each fit, preserving line endings and
    #    hard-splitting any single line longer than the atom limit.
    atoms: List[str] = []
    for line in text.splitlines(keepends=True):
        if len(line) <= atom_limit:
            atoms.append(line)
        else:
            for i in range(0, len(line), atom_limit):
                atoms.append(line[i:i + atom_limit])

    # 2. Greedily pack atoms into chunks of at most atom_limit characters.
    raw_chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0
    for atom in atoms:
        if buf and buf_len + len(atom) > atom_limit:
            raw_chunks.append("".join(buf))
            buf = []
            buf_len = 0
        buf.append(atom)
        buf_len += len(atom)
    if buf:
        raw_chunks.append("".join(buf))

    # 3. Balance <pre> tags across chunks.
    chunks: List[str] = []
    open_pre = False
    for raw in raw_chunks:
        prefix = "<pre>" if open_pre else ""
        net = (1 if open_pre else 0) + raw.count("<pre>") - raw.count("</pre>")
        suffix = "</pre>" if net > 0 else ""
        chunks.append(prefix + raw + suffix)
        open_pre = net > 0
    return chunks


class PydroidTelegramSender:
    """Dispatches Telegram notifications and deliverables natively inside Pydroid 3."""

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        creds = load_env_credentials()
        self.bot_token = bot_token or creds.get("bot_token", "")
        self.chat_id = chat_id or creds.get("chat_id", "")
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def _sanitize_error(self, err: Any) -> str:
        """Redacts sensitive Telegram bot tokens from error messages and logs (CWE-209 / CWE-532)."""
        msg = str(err)
        if self.bot_token and self.bot_token in msg:
            msg = msg.replace(self.bot_token, "[REDACTED_BOT_TOKEN]")
        return msg

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
        """Sends an HTML/text message to the designated Telegram chat, chunking if necessary."""
        chunks = _chunk_message(text, max_length=4000)

        if dry_run:
            print(f"[Telegram] DRY RUN — Message content ({len(chunks)} chunk(s)):")
            print("-" * 50)
            for idx, chunk in enumerate(chunks, 1):
                if len(chunks) > 1:
                    print(f"--- Chunk [{idx}/{len(chunks)}] ---")
                print(chunk)
            print("-" * 50)
            return True

        if not self.is_configured():
            print("⚠ Telegram credentials missing! Please configure .env with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
            return False

        session = self._get_session()
        all_ok = True
        url = f"{self.api_url}/sendMessage"

        for idx, chunk in enumerate(chunks, 1):
            chunk_prefix = f"<b>[{idx}/{len(chunks)}]</b>\n" if len(chunks) > 1 else ""
            payload = {
                "chat_id": self.chat_id,
                "text": chunk_prefix + chunk,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }

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
                else:
                    print(f"✗ Telegram API Error: {res_data.get('description')}")
                    all_ok = False
            except Exception as e:
                print(f"✗ Telegram request error: {self._sanitize_error(e)}")
                all_ok = False

        return all_ok

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
            print(f"✗ Telegram photo transmission failed: {self._sanitize_error(e)}")
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
            print(f"✗ Telegram document transmission failed: {self._sanitize_error(e)}")
            return False


# Institutional Aliases
TelegramSender = PydroidTelegramSender


def format_telegram_alert(
    top_df: pd.DataFrame,
    breadth: Optional[Dict] = None,
    sectors: Optional[Dict] = None,
    regime: Optional[Dict] = None,
    as_of_date: str = "",
    top_etf_df: Optional[pd.DataFrame] = None,
    delivery_df: Optional[pd.DataFrame] = None,
    universe_label: str = "NIFTY 750",
    db_audit: Optional[Dict] = None,
    benchmark_name: Optional[str] = None,
    regime_info: Optional[Dict] = None,
    **kwargs,
) -> str:
    """Formats institutional Telegram HTML message with v5.5.2 rich sections."""
    if regime is None and regime_info is not None:
        regime = regime_info
    regime = regime or {}
    breadth = breadth or {}
    sectors = sectors or {}

    tp = breadth.get("trend_participation", {})
    hp = breadth.get("high_proximity", {})
    nhl = breadth.get("net_highs_lows", {})
    b_reg = breadth.get("regime", {})

    dmap = {}
    if delivery_df is not None and not delivery_df.empty:
        dmap = delivery_df.set_index("symbol").to_dict(orient="index")

    eff_bm = benchmark_name or (top_df.attrs.get("benchmark") if hasattr(top_df, "attrs") else None) or regime.get("benchmark_name", "NIFTY 500")

    msg = f"🚀 <b>PROJECT MIP — MOMENTUM DESK v5.5.2</b>\n"
    msg += f"📅 <b>Date:</b> <code>{as_of_date}</code> | <b>Universe:</b> <code>{universe_label}</code>\n"
    msg += f"📊 <b>Benchmark:</b> <code>{eff_bm}</code> ({regime.get('label', 'N/A')})\n"
    if regime.get("bm_close") and regime.get("bm_ema20"):
        c = float(regime["bm_close"])
        e = float(regime["bm_ema20"])
        pct = ((c / max(0.01, e)) - 1.0) * 100
        msg += f"📈 <b>Benchmark 20 EMA:</b> ₹{c:,.1f} vs ₹{e:,.1f} ({pct:+.2f}%)\n"

    # Database synchronization status
    audit_data = db_audit or (top_df.attrs.get("db_audit") if hasattr(top_df, "attrs") else None)
    if audit_data:
        if audit_data.get("is_updated"):
            gdrive_str = " | ☁️ Drive Synced" if audit_data.get("gdrive_backed_up") else ""
            msg += f"💾 <b>Database:</b> 🟢 Updated (+{audit_data.get('new_rows_added', 0):,} rows ➔ <code>{audit_data.get('post_latest_date')}</code>{gdrive_str})\n"
        else:
            msg += f"💾 <b>Database:</b> 🔵 Up-to-date (<code>{audit_data.get('post_latest_date')}</code> | {audit_data.get('post_row_count', 0):,} rows)\n"

    res_mom_on = bool(top_df.attrs.get("residual_momentum_enabled")) if hasattr(top_df, "attrs") else False
    overlays_badges = []
    if res_mom_on:
        overlays_badges.append("Residual Alpha (40/60 Split)")
    if delivery_df is not None and not delivery_df.empty:
        overlays_badges.append("Delivery Veto (Active)")
    if overlays_badges:
        msg += f"🛡️ <b>ALPHA OVERLAYS & RISK SHIELD:</b>\n"
        msg += f"• <code>{' | '.join(overlays_badges)}</code>\n\n"
    else:
        msg += "\n"

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
        s_sec = html.escape(str(s.get('sector', '')), quote=False)
        msg += f"{s.get('rank', 0):<4}{s_sec:<11}{s.get('ret_1m', 0.0):+5.1f}%  {s.get('alpha_1m', 0.0):+5.1f}%  {s.get('breadth_200_pct', 0.0):4.0f}%\n"
    msg += "</pre>\n"

    # Top 10 Stocks with TradingView hyperlinks, residual alpha, and delivery tags
    msg += f"🏆 <b>TOP MOMENTUM STOCKS ({'Residual Alpha' if res_mom_on else 'Volar'} Ranking)</b>\n"
    for idx, (_, r) in enumerate(top_df.head(10).iterrows(), 1):
        sym = r["symbol"]
        px = float(r.get("close", 0.0))
        volar = float(r.get("volar_score", 0.0))
        ret_val = float(r.get("ret_1y", 0.0) or r.get("return_252d", 0.0))
        ret_1y = ret_val if abs(ret_val) > 5.0 or ret_val == 0.0 else ret_val * 100.0
        tv_url = f"https://in.tradingview.com/chart/?symbol=NSE:{sym}"

        sec_val = r.get("sector")
        sec_str = ""
        if pd.notna(sec_val) and str(sec_val).strip():
            sec_esc = html.escape(str(sec_val).strip(), quote=False)
            sec_str = f" ({sec_esc})"

        d_info = dmap.get(sym, {})
        d_per = d_info.get("deliv_per")
        d_times = d_info.get("deliv_times")
        act = d_info.get("deliv_action", "")
        act_badge = " 🟢" if "ACCUMULATION" in act else (" 🔴" if "DISTRIBUTION" in act else "")
        d_str = ""
        if d_per is not None and pd.notna(d_per):
            d_str = f" | Deliv: <code>{d_per:.0f}%</code>{act_badge}"
            if d_times is not None and pd.notna(d_times) and d_times >= 1.5:
                d_str += f" (<b>{d_times:.1f}x</b>)"

        res_str = ""
        if pd.notna(r.get("residual_mom_score")):
            res_str = f" | Res: <code>{float(r['residual_mom_score']):+.2f}</code>"

        msg += f"<code>{idx:02d}.</code> <a href=\"{tv_url}\"><b>{sym}</b></a>{sec_str} — ₹{px:,.1f} | Volar: <code>{volar:.2f}</code>{res_str} | 1Y: <code>{ret_1y:+.1f}%</code>{d_str}\n"

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

    msg += f"\n<i>Generated natively via Project MIP Institutional Engine</i>"
    return msg
