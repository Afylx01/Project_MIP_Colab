"""
colab/environment.py - Google Colab Environment Setup, Drive Mount & Fast NVMe Database Staging
Modularizes Cell 1 into a clean, testable routine.
"""

import os
import sys
import platform
import shutil
import time
import subprocess
from pathlib import Path
from typing import Dict, Any, Tuple


def is_in_colab() -> bool:
    """Checks whether execution is occurring within Google Colab."""
    return "google.colab" in sys.modules or Path("/content").exists()


def is_gzipped_file(file_path: Path) -> bool:
    """Detects whether a file begins with gzip magic bytes."""
    p = Path(file_path)
    if not p.exists() or p.stat().st_size < 2:
        return False
    try:
        with open(p, "rb") as f:
            return f.read(2) == b"\x1f\x8b"
    except Exception:
        return False


def decompress_file(src_gz: Path, dest_raw: Path) -> Tuple[int, int]:
    """Decompresses a gzip archive to a destination file safely via a temp file."""
    import gzip
    src, dest = Path(src_gz), Path(dest_raw)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f"{dest.name}.tmp_decomp_{int(time.time())}"
    with gzip.open(src, "rb") as f_in, open(tmp, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    tmp.replace(dest)
    return src.stat().st_size, dest.stat().st_size


def setup_colab_environment(
    verbose: bool = True,
    mount_drive: bool = True,
    download_if_missing: bool = True,
) -> Dict[str, Any]:
    """
    Probes cloud compute environment, mounts Google Drive, stages universe.db
    to local NVMe SSD, verifies database integrity, and benchmarks storage latency.
    """
    if verbose:
        print("🔍 PROBING CLOUD COMPUTE ENVIRONMENT...")
        print(f"  • Platform:     {platform.platform()}")
        print(f"  • Python:       {sys.version.split()[0]}")
        print(f"  • Architecture: {platform.machine()}")
        print(f"  • CPU Cores:    {os.cpu_count()}")

    in_colab = is_in_colab()
    workspace_dir = Path("/content/Project_MIP_Colab") if in_colab and Path("/content/Project_MIP_Colab").exists() else Path.cwd()

    if str(workspace_dir) not in sys.path:
        sys.path.insert(0, str(workspace_dir))

    # Mount Google Drive if in Colab
    if in_colab and mount_drive and not Path("/content/drive/MyDrive").exists():
        if verbose:
            print("\n📁 Mounting Google Drive...")
        try:
            from google.colab import drive
            drive.mount("/content/drive")
        except Exception as e:
            if verbose:
                print(f"Drive mount notice: {e}")

    # Synchronize universe.db from Google Drive with gzip decompression
    from scripts.cloud_sync import (
        sync_universe_from_gdrive,
        benchmark_storage_latency,
        PUBLIC_UNIVERSE_DB_FILE_ID,
        PUBLIC_UNIVERSE_DB_URL,
    )
    from core.data_engine import get_db_path, get_universe_statistics

    if verbose:
        print("\n⚡ Staging universe.db to local NVMe storage (with gzip decompress)...")
    ok, status, meta = sync_universe_from_gdrive(verbose=verbose)

    db_target = get_db_path()
    if not db_target.exists() and in_colab and download_if_missing:
        if verbose:
            print(f"\n📥 Downloading universe.db directly via Google Drive File ID ({PUBLIC_UNIVERSE_DB_FILE_ID})...")
        try:
            subprocess.run(["gdown", "--id", PUBLIC_UNIVERSE_DB_FILE_ID, "-O", str(db_target)], check=True)
            if db_target.exists() and is_gzipped_file(db_target):
                if verbose:
                    print("  • Decompressing downloaded gzip archive to SQLite...")
                decompress_file(db_target, db_target)
        except Exception as e_down:
            if verbose:
                print(f"Download notice: {e_down}")

    report = {
        "in_colab": in_colab,
        "workspace_dir": str(workspace_dir),
        "db_exists": db_target.exists(),
        "db_path": str(db_target),
    }

    if db_target.exists():
        stats = get_universe_statistics()
        bm = benchmark_storage_latency(db_target, num_queries=20)
        report.update({
            "total_rows": stats["total_rows"],
            "unique_symbols": stats["unique_symbols"],
            "min_date": stats["min_date"],
            "max_date": stats["max_date"],
            "file_size_mb": stats["file_size_mb"],
            "avg_latency_ms": bm["avg_latency_ms"],
            "is_nvme_grade": bm["is_nvme_grade"],
        })
        if verbose:
            print("\n✓ DATABASE INTEGRITY CONFIRMED:")
            print(f"  • Total Rows:      {stats['total_rows']:,}")
            print(f"  • Unique Symbols:  {stats['unique_symbols']}")
            print(f"  • Date Span:       {stats['min_date']} → {stats['max_date']}")
            print(f"  • Local NVMe Size: {stats['file_size_mb']:.2f} MB")
            print("\n⚡ Benchmarking Storage Latency...")
            print(f"  • Average Latency: {bm['avg_latency_ms']:.2f} ms ({'NVMe Ultra-Fast' if bm['is_nvme_grade'] else 'Network-Bound'})")
    else:
        if verbose:
            print("\n⚠ universe.db not found on Google Drive.")
            print(f"ℹ Direct Download Link: {PUBLIC_UNIVERSE_DB_URL}")
            print("  Or run: !gdown --id 19LaJGbeVx2lx9RytT0vig0Srqc6G4Q65 -O data/universe.db")

    return report
