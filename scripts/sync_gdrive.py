#!/usr/bin/env python3
"""
Project MIP Google Drive Synchronization Utility
Usage:
  python scripts/sync_gdrive.py [--source /path/to/drive/universe.db] [--benchmark]
"""

import sys
import argparse
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.cloud_sync import sync_universe_from_gdrive, benchmark_storage_latency, is_running_in_colab
from core.data_engine import get_db_path, get_universe_statistics


def main():
    parser = argparse.ArgumentParser(description="Project MIP Google Drive & Cloud Staging CLI")
    parser.add_argument("--source", type=str, default=None, help="Explicit path to source universe.db in Google Drive")
    parser.add_argument("--destination", type=str, default=None, help="Destination path on local NVMe (default: data/universe.db)")
    parser.add_argument("--file-id", type=str, default=None, help="Google Drive File ID for universe.db")
    parser.add_argument("--benchmark", action="store_true", help="Run latency benchmark on database after staging")
    args = parser.parse_args()

    print("=" * 70)
    print(" PROJECT MIP: GOOGLE DRIVE & HIGH-SPEED NVME STAGING ENGINE")
    print("=" * 70)
    print(f"  • Environment: {'Google Colab' if is_running_in_colab() else 'Local Linux / Android'}")
    print(f"  • Target DB:   {args.destination or get_db_path()}")

    ok, status, meta = sync_universe_from_gdrive(
        destination_path=Path(args.destination) if args.destination else None,
        gdrive_source_path=Path(args.source) if args.source else None,
        file_id=args.file_id,
        verbose=True,
    )

    if not ok:
        print(f"\n❌ Staging Failed: {status}")
        print(f"   Diagnostic: {meta.get('help', 'Unknown error')}")
        sys.exit(1)

    print(f"\n✓ Staging Status: {status}")
    db_path = Path(meta.get("destination", get_db_path()))
    if db_path.exists():
        stats = get_universe_statistics()
        print(f"\n✓ Verified Database Statistics:")
        print(f"  • Total Rows:     {stats['total_rows']:,}")
        print(f"  • Unique Symbols: {stats['unique_symbols']}")
        print(f"  • Date Span:      {stats['min_date']} to {stats['max_date']}")
        print(f"  • Size:           {stats['file_size_mb']:.2f} MB")

        if args.benchmark:
            print(f"\n⚡ Running I/O Latency Benchmark...")
            bm = benchmark_storage_latency(db_path, num_queries=20)
            print(f"  • Average Latency: {bm['avg_latency_ms']:.2f} ms")
            print(f"  • Min / Max:       {bm['min_latency_ms']:.2f} ms / {bm['max_latency_ms']:.2f} ms")
            print(f"  • Performance:     {'NVMe Ultra-Fast (<5ms)' if bm['is_nvme_grade'] else 'Network / FUSE Bound (>5ms)'}")

    print("=" * 70)


if __name__ == "__main__":
    main()
