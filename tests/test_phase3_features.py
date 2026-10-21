"""
tests/test_phase3_features.py
TDD Test Suite for Phase 3: Automation & Configuration Unification
1. UserProfile Schema, Loading, Saving, and Validation (core/profile.py).
2. Configuration Invariant Guards (capital > 0, weights sum to 1.0, top_n bounds).
3. Headless End-Of-Day Runner (scripts/eod_headless_runner.py).
"""

import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from nextgen.profile import (
    UserProfile,
    load_user_profile,
    save_user_profile,
    get_default_profile,
    ProfileValidationError,
)
from scripts.eod_headless_runner import EODHeadlessRunner


class TestUserProfileConfiguration:
    """Verifies UserProfile data model, serialization, and validation invariants."""

    def test_default_profile_invariants(self):
        """Default profile must be institutional, self-consistent, and pass all validations."""
        profile = get_default_profile()
        assert profile.portfolio.capital == 1_000_000.0
        assert profile.portfolio.top_n == 20
        assert profile.portfolio.exit_buffer_rank == 40
        assert profile.alpha_model.weights["total_momentum"] == 0.45
        assert profile.alpha_model.weights["residual_momentum"] == 0.35
        assert profile.alpha_model.weights["delivery_flow"] == 0.20
        assert profile.execution_guards.upper_circuit_veto is True
        assert profile.execution_guards.delivery_distribution_veto is True
        assert profile.execution_guards.deadband_inr == 2500.0
        assert profile.execution_guards.tax_aware_rebalance is True

        is_valid, errors = profile.validate()
        assert is_valid, f"Default profile failed validation: {errors}"
        assert len(errors) == 0

    def test_profile_validation_rejects_negative_capital(self):
        """Capital must be strictly positive."""
        profile = get_default_profile()
        profile.portfolio.capital = -5000.0
        is_valid, errors = profile.validate()
        assert not is_valid
        assert any("capital" in err.lower() for err in errors)

    def test_profile_validation_rejects_unbalanced_alpha_weights(self):
        """Alpha model factor weights must sum to 1.0 ± 0.001."""
        profile = get_default_profile()
        profile.alpha_model.weights = {
            "total_momentum": 0.50,
            "residual_momentum": 0.50,
            "delivery_flow": 0.50,  # Sum = 1.50
        }
        is_valid, errors = profile.validate()
        assert not is_valid
        assert any("weights" in err.lower() for err in errors)

    def test_profile_validation_rejects_exit_buffer_below_top_n(self):
        """Exit buffer rank cannot be smaller than top_n."""
        profile = get_default_profile()
        profile.portfolio.top_n = 20
        profile.portfolio.exit_buffer_rank = 10  # Invalid! Buffer must be >= top_n
        is_valid, errors = profile.validate()
        assert not is_valid
        assert any("buffer" in err.lower() for err in errors)

    def test_save_and_load_round_trip(self, tmp_path):
        """Serializing and deserializing profile preserves exact typed parameters."""
        profile = get_default_profile()
        profile.user_name = "Institutional Desk A"
        profile.portfolio.capital = 2_500_000.0
        profile.portfolio.universe = "NIFTY100"

        test_file = tmp_path / "custom_user_profile.json"
        save_user_profile(profile, test_file)

        assert test_file.exists()
        loaded = load_user_profile(test_file)
        assert loaded.user_name == "Institutional Desk A"
        assert loaded.portfolio.capital == 2_500_000.0
        assert loaded.portfolio.universe == "NIFTY100"
        assert loaded.execution_guards.deadband_inr == 2500.0

    def test_load_non_existent_profile_falls_back_or_creates_default(self, tmp_path):
        """Loading from non-existent file returns default profile gracefully."""
        non_existent = tmp_path / "does_not_exist.json"
        profile = load_user_profile(non_existent)
        assert profile is not None
        assert profile.portfolio.capital == 1_000_000.0


class TestEODHeadlessRunner:
    """Verifies end-of-day headless execution pipeline for automated cron jobs."""

    def test_headless_runner_initialization_with_profile(self):
        """EODHeadlessRunner binds to user profile and exposes execution hooks."""
        profile = get_default_profile()
        runner = EODHeadlessRunner(base_dir=BASE_DIR, profile=profile)
        assert runner.profile.portfolio.capital == 1_000_000.0
        assert runner.base_dir == BASE_DIR

    def test_headless_runner_dry_run_executes_pipeline(self, tmp_path):
        """Dry-run execution validates pre-flight health, runs scan/rebalance mock, and emits telemetry."""
        profile = get_default_profile()
        profile.automation.auto_fetch_latest = False  # Avoid network call in test
        profile.automation.generate_kite_basket = True

        runner = EODHeadlessRunner(base_dir=BASE_DIR, profile=profile, reports_dir=tmp_path)
        result = runner.run_eod_pipeline(dry_run=True, skip_health_check=True)

        assert result["status"] == "SUCCESS"
        assert "execution_timestamp" in result
        assert result["capital"] == 1_000_000.0
        assert "telemetry_file" in result
        assert Path(result["telemetry_file"]).exists()

    def test_headless_runner_forwards_sizing_and_sector_guards(self, tmp_path):
        """Verifies that as_of_date, sizing_mode, and max_sector_allocation are passed to generate_rebalance_orders."""
        profile = get_default_profile()
        profile.portfolio.sizing_model = "equal_weight"
        profile.execution_guards.max_sector_allocation = 3

        runner = EODHeadlessRunner(base_dir=BASE_DIR, profile=profile, reports_dir=tmp_path)

        with patch("scripts.run_production_pipeline.HeadlessProductionPipeline.run_pipeline") as mock_run_pipe, \
             patch("core.portfolio.PortfolioManager.generate_rebalance_orders") as mock_rebal, \
             patch("core.portfolio.PortfolioManager.export_kite_basket") as mock_kite:

            mock_run_pipe.return_value = {"pipeline_status": "SUCCESS"}
            mock_rebal.return_value = MagicMock(empty=True)
            mock_rebal.return_value.__len__.return_value = 0
            mock_kite.return_value = (tmp_path / "basket.json", tmp_path / "basket.html")

            result = runner.run_eod_pipeline(dry_run=False, skip_health_check=True, target_date="2026-10-16")
            assert result["status"] == "SUCCESS"

            mock_rebal.assert_called_once()
            _, kwargs = mock_rebal.call_args
            assert kwargs["as_of_date"] == "2026-10-16"
            assert kwargs["sizing_mode"] == "equal_weight"
            assert kwargs["max_per_sector"] == 3
