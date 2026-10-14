"""
MIP Android — Main Application All Indices & 30-Day TTL Integration Tests
Validates that main.py supports all 36 NIFTY indices, CLI universe argument normalization,
30-day cache refresh TTL controls, and the batch execution flow.
"""

import unittest
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.scanner_hardening import NIFTY_INDICES_CATALOG, normalize_universe_mode


class TestMainAllIndicesIntegration(unittest.TestCase):
    """Test CLI argument parsing and all-universe integration in main.py."""

    def test_main_cli_parser_accepts_all_36_universes(self):
        """Verify main.py argument parser accepts all 36 cataloged index keys."""
        import main
        parser = main.build_parser() if hasattr(main, "build_parser") else None
        self.assertIsNotNone(parser, "main.py must expose build_parser() function")

        for idx_key in NIFTY_INDICES_CATALOG.keys():
            args = parser.parse_args(["--universe", idx_key])
            norm = main.resolve_target_universe(args.universe) if hasattr(main, "resolve_target_universe") else normalize_universe_mode(args.universe)
            self.assertEqual(norm, idx_key, f"CLI must normalize {idx_key} to {idx_key}")

    def test_main_cli_parser_accepts_aliases(self):
        """Verify main.py CLI accepts aliases like bank, it, cpse, 750."""
        import main
        parser = main.build_parser() if hasattr(main, "build_parser") else None
        self.assertIsNotNone(parser, "main.py must expose build_parser() function")

        test_cases = [
            ("bank", "NIFTYBANK"),
            ("it", "NIFTYIT"),
            ("auto", "NIFTYAUTO"),
            ("cpse", "NIFTYCPSE"),
            ("microcap", "NIFTYMICROCAP250"),
            ("750", "NIFTY750"),
            ("500", "NIFTY500"),
            ("all", "ALL"),
        ]
        for alias, expected in test_cases:
            args = parser.parse_args(["--universe", alias])
            norm = main.resolve_target_universe(args.universe) if hasattr(main, "resolve_target_universe") else normalize_universe_mode(args.universe)
            self.assertEqual(norm, expected, f"CLI alias '{alias}' must resolve to '{expected}'")

    def test_main_cli_force_refresh_flag(self):
        """Verify main.py CLI supports --force-refresh."""
        import main
        parser = main.build_parser() if hasattr(main, "build_parser") else None
        self.assertIsNotNone(parser)
        args = parser.parse_args(["--force-refresh"])
        self.assertTrue(args.force_refresh, "--force-refresh must set force_refresh=True")

    def test_main_cli_option_17_and_scan_all_flag(self):
        """Verify main.py CLI supports option 17 and --scan-all-universes."""
        import main
        parser = main.build_parser() if hasattr(main, "build_parser") else None
        self.assertIsNotNone(parser)
        args1 = parser.parse_args(["--option", "17"])
        self.assertEqual(args1.option, 17)
        args2 = parser.parse_args(["--scan-all-universes"])
        self.assertTrue(args2.scan_all_universes)

    def test_main_exposes_run_all_indices_batch_flow(self):
        """Verify main.py defines and exposes run_all_indices_batch_flow."""
        import main
        self.assertTrue(hasattr(main, "run_all_indices_batch_flow"),
                        "main.py must define run_all_indices_batch_flow function")
        self.assertTrue(callable(main.run_all_indices_batch_flow))

    def test_main_scanner_flow_executes_on_sectoral_universe(self):
        """Verify run_scanner_flow runs on NIFTY Bank in non-interactive mode with test isolation."""
        import main
        from unittest.mock import patch, MagicMock

        # Preserve shared live deliverables to ensure test isolation
        csv_path = PROJECT_ROOT / "reports" / "screener_output_live.csv"
        csv_backup = csv_path.read_bytes() if csv_path.exists() else None

        # Mock telegram sender to prevent external network calls during unit test
        mock_sender = MagicMock()
        mock_sender.is_configured.return_value = False

        try:
            with patch("core.telegram_sender.PydroidTelegramSender", return_value=mock_sender):
                main.run_scanner_flow(interactive=False, universe_mode="NIFTYBank")
        except SystemExit as e:
            self.assertEqual(e.code, 0, "run_scanner_flow must exit 0 or complete cleanly")
        finally:
            # Restore canonical screener baseline
            if csv_backup is not None:
                csv_path.write_bytes(csv_backup)


if __name__ == "__main__":
    unittest.main(verbosity=2)

