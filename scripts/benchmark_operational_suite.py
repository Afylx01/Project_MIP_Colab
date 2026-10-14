import sys
import os
import time
import json
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path("C:/Users/Arindam Das/Desktop/project/MIP_Android")
sys.path.insert(0, str(PROJECT_ROOT))

from core.scanner import PydroidScanner
from core.data_engine import load_universe_constituents, get_db_path

benchmarks = {}

# 1. Scanner Initialization Benchmark
t0 = time.perf_counter()
scanner = PydroidScanner(base_dir=PROJECT_ROOT)
t_init = time.perf_counter() - t0
benchmarks["scanner_init_seconds"] = round(t_init, 4)
print(f"Scanner Initialization: {t_init:.4f}s")

# 2. Universe Filtering Benchmark
t0 = time.perf_counter()
symbols_750 = load_universe_constituents(universe_name="750")
t_filter = time.perf_counter() - t0
benchmarks["universe_filter_seconds"] = round(t_filter, 4)
benchmarks["symbols_filtered_count"] = len(symbols_750)
print(f"Universe Filter ({len(symbols_750)} symbols): {t_filter:.4f}s")

# 3. Test Suite Duration Benchmark
import unittest
loader = unittest.TestLoader()
suite = loader.discover(start_dir=str(PROJECT_ROOT / "tests"), pattern="test_*.py")
t0 = time.perf_counter()
runner = unittest.TextTestRunner(verbosity=0)
res = runner.run(suite)
t_suite = time.perf_counter() - t0
benchmarks["test_suite_duration_seconds"] = round(t_suite, 4)
benchmarks["tests_total"] = res.testsRun
benchmarks["tests_passed"] = res.testsRun - len(res.failures) - len(res.errors) - len(res.skipped)
benchmarks["tests_skipped"] = len(res.skipped)
benchmarks["tests_failed"] = len(res.failures)
benchmarks["tests_errored"] = len(res.errors)
print(f"Test Suite Execution ({res.testsRun} tests): {t_suite:.4f}s (Passed: {benchmarks['tests_passed']}, Skipped: {benchmarks['tests_skipped']}, Failed: {benchmarks['tests_failed']})")

out_file = PROJECT_ROOT / "reports" / "operational_benchmarks.json"
out_file.parent.mkdir(parents=True, exist_ok=True)
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(benchmarks, f, indent=2)

print(f"\nSaved benchmarks to {out_file}")
