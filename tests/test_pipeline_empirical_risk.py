"""
tests/test_pipeline_empirical_risk.py
Tests verifying empirical price extraction and fail-closed behavior in dispatch_institutional_pipeline.
"""

import sqlite3
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch
import argparse
import io
import sys

from scripts.dispatch_institutional_pipeline import run_institutional_pipeline
from analytics.institutional_risk import calculate_comprehensive_risk_suite


def test_pipeline_uses_empirical_prices_not_synthetic(monkeypatch, tmp_path, capsys):
    """F-01/F-05/F-14: pipeline must derive risk returns from the DB, never from np.random."""
    db_dir = tmp_path / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "universe.db"

    # Create 30 dates with 2 symbols
    dates = [f"2026-01-{i+1:02d}" for i in range(30)]
    records = []
    # Drift: AAA goes from 100 * (1.01)^i, BBB goes from 200 * (1.005)^i
    drift_aaa = [100.0 * (1.01 ** i) for i in range(30)]
    drift_bbb = [200.0 * (1.005 ** i) for i in range(30)]

    for i, d in enumerate(dates):
        records.append(("AAA", d, drift_aaa[i]))
        records.append(("BBB", d, drift_bbb[i]))

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE prices (symbol TEXT, date TEXT, close REAL)")
        conn.executemany("INSERT INTO prices VALUES (?, ?, ?)", records)

    # Calculate expected equal-weight portfolio returns
    df_fix = pd.DataFrame({
        "date": dates,
        "AAA": drift_aaa,
        "BBB": drift_bbb,
    }).set_index("date")
    ret_df = df_fix.pct_change().dropna()
    expected_returns = ret_df.mean(axis=1).tolist()

    # Patches
    monkeypatch.setattr("scripts.dispatch_institutional_pipeline.PROJECT_ROOT", tmp_path)

    mock_scanner_df = pd.DataFrame({
        "symbol": ["AAA", "BBB"],
        "ret_252": [0.2, 0.3],
        "vol_252": [0.2, 0.3],
        "close": [drift_aaa[-1], drift_bbb[-1]],
        "sector": ["TECH", "TECH"],
    })
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.HardenedScanner.run_scan",
        lambda self, *args, **kwargs: mock_scanner_df
    )
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.OperationalHealthChecker.run_all_checks",
        lambda self: (True, {"status": "HEALTHY"})
    )
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.InstitutionalTearsheetGenerator.generate_html_tearsheet",
        lambda *args, **kwargs: tmp_path / "tearsheet.html"
    )
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.package_institutional_bundle",
        lambda *args, **kwargs: tmp_path / "bundle.zip"
    )

    risk_spy = MagicMock(return_value={"var_95": -0.02, "cvar_95": -0.03, "ulcer_index": 1.5})
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.calculate_comprehensive_risk_suite",
        risk_spy
    )

    args = argparse.Namespace(universe="NIFTY50", benchmark="NIFTY50", top_n=2)
    exit_code = run_institutional_pipeline(args)
    captured = capsys.readouterr()

    assert exit_code == 0
    assert risk_spy.called
    actual_returns = risk_spy.call_args.kwargs["returns"]

    assert len(actual_returns) == 29
    np.testing.assert_allclose(actual_returns, expected_returns, rtol=1e-7, atol=1e-7)

    assert "name 'pd' is not defined" not in captured.out
    assert "[SYNTHETIC_SCENARIO]" not in captured.out


def test_pipeline_fails_closed_when_db_unreadable(monkeypatch, tmp_path):
    """Corrupt or missing DB must not trigger synthetic fallback or render unverified risk metrics."""
    corrupt_db_dir = tmp_path / "data"
    corrupt_db_dir.mkdir(parents=True, exist_ok=True)
    corrupt_db = corrupt_db_dir / "universe.db"
    corrupt_db.write_text("NOT A VALID SQLITE DATABASE FILE")

    monkeypatch.setattr("scripts.dispatch_institutional_pipeline.PROJECT_ROOT", tmp_path)

    mock_scanner_df = pd.DataFrame({
        "symbol": ["AAA", "BBB"],
        "ret_252": [0.2, 0.3],
        "vol_252": [0.2, 0.3],
        "close": [100.0, 200.0],
        "sector": ["TECH", "TECH"],
    })
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.HardenedScanner.run_scan",
        lambda self, *args, **kwargs: mock_scanner_df
    )
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.OperationalHealthChecker.run_all_checks",
        lambda self: (True, {"status": "HEALTHY"})
    )

    risk_spy = MagicMock(return_value={"var_95": -0.02})
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.calculate_comprehensive_risk_suite",
        risk_spy
    )

    tearsheet_spy = MagicMock(return_value=tmp_path / "tearsheet.html")
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.InstitutionalTearsheetGenerator.generate_html_tearsheet",
        tearsheet_spy
    )
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.package_institutional_bundle",
        lambda *args, **kwargs: tmp_path / "bundle.zip"
    )

    args = argparse.Namespace(universe="NIFTY50", benchmark="NIFTY50", top_n=2)
    exit_code = run_institutional_pipeline(args)

    assert exit_code != 0
    # calculate_comprehensive_risk_suite must NOT have been called with synthetic returns
    assert not risk_spy.called
    tearsheet_call = tearsheet_spy.call_args
    passed_risk = tearsheet_call.kwargs["risk_metrics"] if "risk_metrics" in tearsheet_call.kwargs else tearsheet_call[1].get("risk_metrics", tearsheet_call[0][1])
    assert passed_risk.get("scenario_type") == "UNAVAILABLE"


def test_unavailable_risk_metrics_never_reach_tearsheet_as_kpis(monkeypatch, tmp_path, capsys):
    """Corrupt DB fixture; real InstitutionalTearsheetGenerator must render RISK METRICS UNAVAILABLE and no fabricated KPIs."""
    corrupt_db_dir = tmp_path / "data"
    corrupt_db_dir.mkdir(parents=True, exist_ok=True)
    corrupt_db = corrupt_db_dir / "universe.db"
    corrupt_db.write_text("NOT A VALID SQLITE DATABASE FILE")

    monkeypatch.setattr("scripts.dispatch_institutional_pipeline.PROJECT_ROOT", tmp_path)

    mock_scanner_df = pd.DataFrame({
        "symbol": ["AAA", "BBB"],
        "ret_252": [0.2, 0.3],
        "vol_252": [0.2, 0.3],
        "close": [100.0, 200.0],
        "sector": ["TECH", "TECH"],
    })
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.HardenedScanner.run_scan",
        lambda self, *args, **kwargs: mock_scanner_df
    )
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.OperationalHealthChecker.run_all_checks",
        lambda self: (True, {"status": "HEALTHY"})
    )
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.package_institutional_bundle",
        lambda *args, **kwargs: tmp_path / "bundle.zip"
    )

    args = argparse.Namespace(universe="NIFTY50", benchmark="NIFTY50", top_n=2)
    exit_code = run_institutional_pipeline(args)
    captured = capsys.readouterr()

    # Must return non-zero code when risk metrics fail closed as UNAVAILABLE
    assert exit_code != 0

    reports_dir = tmp_path / "reports"
    html_files = list(reports_dir.glob("MIP_Institutional_Tearsheet_*.html"))
    assert len(html_files) >= 1
    content = html_files[0].read_text(encoding="utf-8")

    assert "RISK METRICS UNAVAILABLE" in content
    assert "COMPLIANT" not in content and "E1_GOLD_SEAL" not in content
    for fabricated in ["28.50", "1.35", "2.15", "1.48", "19.20", "1.85", "2.65", "4.12", "2.50"]:
        assert fabricated not in content


def test_risk_metrics_fail_closed_without_benchmark_and_suppress_stale_symbols(monkeypatch, tmp_path, capsys):
    """Fixture: 2 symbols, 300 daily rows; BBB stops 120 sessions before the target and has no rows afterwards.
    Without benchmark returns, IR and Beta must render N/A and return series must not contain 120 trailing zeros."""
    db_dir = tmp_path / "data"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "universe.db"

    dates = [f"2025-01-01_{i:03d}" for i in range(300)]
    records = []
    # AAA trades all 300 sessions
    for i, d in enumerate(dates):
        records.append(("AAA", d, 100.0 * (1.01 ** (i + 1))))
    # BBB stops 120 sessions before the target (only trades sessions 0..179)
    for i, d in enumerate(dates[:180]):
        records.append(("BBB", d, 200.0 * (1.005 ** (i + 1))))

    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE prices (symbol TEXT, date TEXT, close REAL)")
        conn.executemany("INSERT INTO prices VALUES (?, ?, ?)", records)

    monkeypatch.setattr("scripts.dispatch_institutional_pipeline.PROJECT_ROOT", tmp_path)

    mock_scanner_df = pd.DataFrame({
        "symbol": ["AAA", "BBB"],
        "ret_252": [0.2, 0.3],
        "vol_252": [0.2, 0.3],
        "close": [100.0, 200.0],
        "sector": ["TECH", "TECH"],
    })
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.HardenedScanner.run_scan",
        lambda self, *args, **kwargs: mock_scanner_df
    )
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.OperationalHealthChecker.run_all_checks",
        lambda self: (True, {"status": "HEALTHY"})
    )
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.package_institutional_bundle",
        lambda *args, **kwargs: tmp_path / "bundle.zip"
    )

    risk_spy = MagicMock(wraps=calculate_comprehensive_risk_suite)
    monkeypatch.setattr(
        "scripts.dispatch_institutional_pipeline.calculate_comprehensive_risk_suite",
        risk_spy
    )

    args = argparse.Namespace(universe="NIFTY50", benchmark="NON_EXISTENT_BENCHMARK", top_n=2, as_of_date=dates[-1])
    exit_code = run_institutional_pipeline(args)

    assert risk_spy.called
    called_returns = risk_spy.call_args.kwargs["returns"]
    # Check that called_returns does not contain trailing zeros from forward-filling stale BBB
    trailing_120 = called_returns[-120:]
    assert not any(abs(r) < 1e-9 for r in trailing_120), "Trailing returns must not contain 0.0 values from halted/stale symbol"

    reports_dir = tmp_path / "reports"
    html_files = list(reports_dir.glob("MIP_Institutional_Tearsheet_*.html"))
    assert len(html_files) >= 1
    content = html_files[0].read_text(encoding="utf-8")

    # (a) tearsheet HTML contains HINDSIGHT / scenario disclosure
    assert "HINDSIGHT" in content or "EMPIRICAL" in content
    # (b) does NOT contain Beta: 1.00 or Information Ratio as a measured value when no benchmark supplied - must say N/A
    assert "Beta: 1.00" not in content
    assert "Information Ratio</div>\n            <div class=\"kpi-val\">0.00" not in content
    assert "Beta: N/A" in content or "N/A" in content
