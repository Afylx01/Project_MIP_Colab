"""
cache/fast_cache.py - High-Performance Intermediate Data Caching Layer
Project MIP Institutional Edition (AQR / Two Sigma HPC Standard)

Provides sub-millisecond zero-redundancy dataframe caching for universe queries,
incorporating dual-tier serialization (Apache Arrow / Parquet with pure-NumPy fallback)
and cryptographic database fingerprint invalidation.
"""

from __future__ import annotations

import os
import sys
import time
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import pandas as pd
import numpy as np

logger = logging.getLogger("FastDataCache")

# Optional PyArrow acceleration
try:
    import pyarrow as pa
    import pyarrow.feather as feather
    HAS_PYARROW = True
except ImportError:
    HAS_PYARROW = False


class FastDataCache:
    """
    High-speed intermediate dataframe caching engine.
    Stores and retrieves historical market bars and indicator tensors with
    cryptographic database state invalidation.
    """

    def __init__(self, cache_dir: Optional[Path] = None, max_cache_size_mb: int = 500):
        if cache_dir is None:
            # Default to data/.cache in repository
            repo_root = Path(__file__).resolve().parent.parent
            self.cache_dir = repo_root / "data" / ".cache"
        else:
            self.cache_dir = Path(cache_dir)

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_cache_size_bytes = max_cache_size_mb * 1024 * 1024
        self.metadata_file = self.cache_dir / "cache_manifest.json"
        self._manifest: Dict[str, Any] = self._load_manifest()

    def _load_manifest(self) -> Dict[str, Any]:
        if self.metadata_file.exists():
            try:
                return json.loads(self.metadata_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_manifest(self) -> None:
        try:
            tmp_file = self.metadata_file.with_suffix(f".tmp_{os.getpid()}_{time.time_ns()}")
            tmp_file.write_text(json.dumps(self._manifest, indent=2), encoding="utf-8")
            tmp_file.replace(self.metadata_file)
        except Exception as e:
            logger.warning(f"Failed to persist cache manifest: {e}")

    def compute_cache_key(
        self,
        db_path: Path,
        table_name: str,
        start_date: Optional[str],
        end_date: Optional[str],
        symbols: Optional[List[str]] = None,
        extra_tag: str = "",
    ) -> str:
        """
        Computes a cryptographic SHA-256 fingerprint for the query parameters
        and underlying database file state (size + mtime, including WAL/SHM).
        """
        db_stat = db_path.stat() if db_path.exists() else None
        wal_path = Path(f"{db_path}-wal")
        wal_stat = wal_path.stat() if wal_path.exists() else None
        db_sig_parts = [f"{db_stat.st_size}_{db_stat.st_mtime}" if db_stat else "no_db"]
        if wal_stat:
            db_sig_parts.append(f"wal_{wal_stat.st_size}_{wal_stat.st_mtime}")
        db_signature = "|".join(db_sig_parts)

        sym_str = ",".join(sorted(symbols)) if symbols else "ALL_SYMBOLS"
        sym_hash = hashlib.sha256(sym_str.encode("utf-8")).hexdigest()[:16]

        raw_key = (
            f"db={db_signature}|tbl={table_name}|s={start_date}|e={end_date}|"
            f"syms={sym_hash}|tag={extra_tag}"
        )
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def make_key(self, query_name: str, params: Optional[Dict[str, Any]] = None) -> str:
        param_str = json.dumps(params or {}, sort_keys=True)
        return hashlib.sha256(f"{query_name}:{param_str}".encode("utf-8")).hexdigest()

    def get(
        self,
        cache_key: str,
    ) -> Optional[pd.DataFrame]:
        """
        Retrieves cached DataFrame if exists and valid.
        """
        if cache_key not in self._manifest:
            return None

        entry = self._manifest[cache_key]
        filename = entry.get("filename")
        if not filename:
            return None

        filepath = self.cache_dir / filename
        if not filepath.exists():
            return None

        try:
            fmt = entry.get("format", "feather")
            if fmt == "feather" and HAS_PYARROW:
                df = feather.read_feather(filepath)
            elif fmt == "parquet":
                df = pd.read_parquet(filepath)
            elif fmt == "npz":
                # Fallback numpy format without pickle
                with np.load(filepath, allow_pickle=False) as data:
                    raw_cols = list(data["columns"])
                    cols = [c.decode("utf-8") if isinstance(c, bytes) else str(c) for c in raw_cols]
                    records = {}
                    for col in cols:
                        arr = data[col]
                        null_key = f"__null_{col}"
                        if null_key in data:
                            mask = data[null_key]
                            if arr.dtype.kind in ('U', 'S', 'O'):
                                s_series = pd.Series(arr, dtype=object)
                                s_series[mask] = np.nan
                                records[col] = s_series
                            else:
                                records[col] = np.where(mask, np.nan, arr)
                        else:
                            records[col] = arr
                    df = pd.DataFrame(records)
            else:
                return None

            # Update last accessed in-memory
            entry["last_accessed"] = time.time()
            return df
        except Exception as e:
            logger.warning(f"Failed to read cache file {filepath}: {e}. Evicting corrupted cache entry.")
            self._manifest.pop(cache_key, None)
            try:
                if filepath.exists():
                    filepath.unlink()
            except OSError:
                pass
            self._save_manifest()
            return None

    def store(
        self,
        cache_key: str,
        df: pd.DataFrame,
        description: str = "",
        preferred_format: str = "auto",
    ) -> bool:
        """
        Atomically stores DataFrame to cache with format auto-selection.
        """
        if df is None or df.empty:
            return False

        self._enforce_size_limit()

        try:
            use_feather = (preferred_format == "auto" or preferred_format == "feather") and HAS_PYARROW
            if use_feather:
                fmt = "feather"
                filename = f"{cache_key}.feather"
                filepath = self.cache_dir / filename
                tmp_path = filepath.with_suffix(f".tmp_{os.getpid()}_{time.time_ns()}")
                # Reset index for clean feather storage
                export_df = df.reset_index() if isinstance(df.index, pd.DatetimeIndex) else df.copy()
                feather.write_feather(export_df, tmp_path, compression="zstd")
                tmp_path.replace(filepath)
            else:
                # Pure numpy/python fallback without pickle
                fmt = "npz"
                filename = f"{cache_key}.npz"
                filepath = self.cache_dir / filename
                tmp_path = self.cache_dir / f"{cache_key}_{os.getpid()}_{time.time_ns()}.tmp.npz"
                arrays_to_save: Dict[str, Any] = {"columns": np.array([str(c) for c in df.columns], dtype=str)}
                for col in df.columns:
                    s = df[col]
                    col_str = str(col)
                    if s.isna().any():
                        arrays_to_save[f"__null_{col_str}"] = s.isna().to_numpy()
                    if s.dtype == object or pd.api.types.is_string_dtype(s):
                        arrays_to_save[col_str] = np.array(s.fillna("").astype(str), dtype=str)
                    else:
                        arrays_to_save[col_str] = s.to_numpy()
                np.savez_compressed(tmp_path, **arrays_to_save)
                tmp_path.replace(filepath)

            file_size = filepath.stat().st_size

            # A single entry larger than the configured budget cannot be cached
            # without violating the limit; reject it instead of silently overshooting.
            if self.max_cache_size_bytes > 0 and file_size > self.max_cache_size_bytes:
                try:
                    filepath.unlink()
                except OSError:
                    pass
                logger.warning(
                    "Cache entry %.2f MB exceeds max_cache_size %.2f MB; not stored.",
                    file_size / (1024 * 1024), self.max_cache_size_bytes / (1024 * 1024),
                )
                return False

            disk_manifest = self._load_manifest()
            disk_manifest.update(self._manifest)
            self._manifest = disk_manifest
            self._manifest[cache_key] = {
                "filename": filename,
                "format": fmt,
                "size_bytes": file_size,
                "rows": len(df),
                "cols": len(df.columns),
                "description": description,
                "created_at": time.time(),
                "last_accessed": time.time(),
            }
            self._save_manifest()
            self._enforce_size_limit()
            return True
        except Exception as e:
            logger.warning(f"Failed to store cache entry {cache_key}: {e}")
            return False

    def _enforce_size_limit(self) -> None:
        """Evicts oldest entries when cache exceeds max_cache_size_bytes."""
        total_size = sum(e.get("size_bytes", 0) for e in self._manifest.values())
        if total_size <= self.max_cache_size_bytes:
            return

        # Sort by last_accessed ascending
        sorted_keys = sorted(
            self._manifest.keys(),
            key=lambda k: self._manifest[k].get("last_accessed", 0),
        )

        for k in sorted_keys:
            if total_size <= self.max_cache_size_bytes * 0.8:
                break
            entry = self._manifest.pop(k)
            fname = entry.get("filename")
            if fname:
                fpath = self.cache_dir / fname
                if fpath.exists():
                    try:
                        sz = fpath.stat().st_size
                        fpath.unlink()
                        total_size -= sz
                    except OSError:
                        pass
        self._save_manifest()

    def clear(self) -> int:
        """Clears all cached files and resets manifest. Returns count of files deleted."""
        count = 0
        for entry in self._manifest.values():
            fname = entry.get("filename")
            if fname:
                fpath = self.cache_dir / fname
                if fpath.exists():
                    try:
                        fpath.unlink()
                        count += 1
                    except OSError:
                        pass
        self._manifest.clear()
        self._save_manifest()
        return count
