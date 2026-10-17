"""
bridge.py - Native C99 Compiler & High-Speed ctypes Dispatcher for Project MIP Brute Force
"""

import os
import sys
import shutil
import tempfile
import subprocess
import ctypes
import platform
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np

BRUTE_FORCE_DIR = Path(__file__).resolve().parent
C_SOURCE = BRUTE_FORCE_DIR / "sim_kernel.c"


def get_so_target_path() -> Path:
    """
    Dynamically identifies an ext4, writable, executable directory for mip_sim_kernel.so.
    Supports Pydroid 3, Termux PRoot, Termux native, Google Colab, and standard Linux.
    Strictly avoids Android's noexec /storage/emulated/0 filesystem.
    """
    candidates = []

    # 1. Environment variables (TMPDIR is explicitly set by Pydroid 3 and Termux)
    for var in ("TMPDIR", "TEMP", "TMP"):
        val = os.environ.get(var)
        if val:
            candidates.append(Path(val))

    # 2. Pydroid 3 internal app storage derived from sys.prefix
    if hasattr(sys, "prefix") and sys.prefix:
        pfx = Path(sys.prefix)
        # In Pydroid 3, sys.prefix is /data/user/0/ru.iiec.pydroid3/files
        candidates.append(pfx / "cache")
        candidates.append(pfx / "temp")
        candidates.append(pfx)
        if pfx.parent:
            candidates.append(pfx.parent / "cache")
            candidates.append(pfx.parent / "files")

    # 3. Known Pydroid 3 standard internal storage paths
    candidates.extend([
        Path("/data/user/0/ru.iiec.pydroid3/cache"),
        Path("/data/data/ru.iiec.pydroid3/cache"),
        Path("/data/user/0/ru.iiec.pydroid3/files"),
        Path("/data/data/ru.iiec.pydroid3/files"),
    ])

    # 4. Standard Python tempfile directory
    try:
        candidates.append(Path(tempfile.gettempdir()))
    except Exception:
        pass

    # 5. Linux /tmp (PRoot Ubuntu, Google Colab, Debian/Ubuntu)
    candidates.append(Path("/tmp"))

    # 6. User home directory cache
    try:
        candidates.append(Path.home() / ".cache" / "mip")
    except Exception:
        pass

    # Directories that are mounted noexec on Android (dlopen will fail even if writable)
    noexec_prefixes = (
        "/storage/emulated",
        "/mnt/sdcard",
        "/sdcard",
        "/storage/self",
    )

    for cand in candidates:
        try:
            cand_resolved = cand.resolve() if cand.exists() else cand
            cand_str = str(cand_resolved)
            # Skip any paths residing on Android emulated / external storage
            if any(cand_str.startswith(p) for p in noexec_prefixes):
                continue

            cand.mkdir(parents=True, exist_ok=True)
            test_file = cand / f".mip_probe_{os.getpid()}"
            test_file.write_text("ok")
            test_file.unlink()
            return cand / "mip_sim_kernel.so"
        except (PermissionError, OSError):
            continue

    # Fallback to /tmp
    return Path("/tmp/mip_sim_kernel.so")


SO_TARGET = get_so_target_path()


def get_compiler_bin() -> str:
    """Finds available C compiler binary (gcc or clang) across environments."""
    for cand in ("gcc", "clang", "aarch64-linux-android-gcc", "aarch64-linux-gnu-gcc"):
        which = shutil.which(cand)
        if which:
            return which

    # Check common Pydroid 3 and Termux locations explicitly
    for fixed in (
        "/data/data/ru.iiec.pydroid3/files/bin/gcc",
        "/data/user/0/ru.iiec.pydroid3/files/bin/gcc",
        "/data/data/ru.iiec.pydroid3/files/bin/clang",
        "/data/user/0/ru.iiec.pydroid3/files/bin/clang",
        "/data/data/com.termux/files/usr/bin/gcc",
        "/data/data/com.termux/files/usr/bin/clang",
        "/usr/bin/gcc",
        "/usr/bin/clang",
    ):
        if os.path.exists(fixed) and os.access(fixed, os.X_OK):
            return fixed

    return "gcc"

# Filter Bitmask Constants matching sim_kernel.c
FILTER_RETRACE       = (1 << 0) # 0x01
FILTER_TREND         = (1 << 1) # 0x02
FILTER_RS            = (1 << 2) # 0x04
FILTER_REGIME        = (1 << 3) # 0x08
FILTER_SECTOR_CAP    = (1 << 4) # 0x10
FILTER_RESIDUAL_MOM  = (1 << 5) # 0x20
FILTER_VOL_TARGETING = (1 << 6) # 0x40
FILTER_DELIVERY_VETO = (1 << 7) # 0x80

# Canonical Baseline Bitmask (all 5 core filters active, Volar momentum)
CANONICAL_FILTER_FLAGS = FILTER_RETRACE | FILTER_TREND | FILTER_RS | FILTER_REGIME | FILTER_SECTOR_CAP

# Rebalancing Schedule Enums
SCHEDULE_WEEKLY      = 0
SCHEDULE_MONTHLY     = 1
SCHEDULE_QUARTERLY   = 2
SCHEDULE_HALF_YEARLY = 3
SCHEDULE_YEARLY      = 4

SCHEDULE_MAP = {
    "weekly": SCHEDULE_WEEKLY,
    "monthly": SCHEDULE_MONTHLY,
    "quarterly": SCHEDULE_QUARTERLY,
    "half_yearly": SCHEDULE_HALF_YEARLY,
    "yearly": SCHEDULE_YEARLY,
    "annual": SCHEDULE_YEARLY,
}


# 48-byte Result Struct matching C99 SimulationSummary
class CSimulationSummary(ctypes.Structure):
    _fields_ = [
        ("param_id", ctypes.c_uint32),
        ("cagr", ctypes.c_float),
        ("sharpe", ctypes.c_float),
        ("sortino", ctypes.c_float),
        ("max_drawdown", ctypes.c_float),
        ("calmar", ctypes.c_float),
        ("win_rate", ctypes.c_float),
        ("profit_factor", ctypes.c_float),
        ("ending_equity", ctypes.c_float),
        ("total_trades", ctypes.c_uint32),
        ("winning_trades", ctypes.c_uint32),
        ("turnover_annual", ctypes.c_float),
    ]


# 64-byte Parameter Specification matching C99 SimParams
class CSimParams(ctypes.Structure):
    _fields_ = [
        ("param_id", ctypes.c_uint32),
        ("schedule_idx", ctypes.c_uint32),
        ("start_date_idx", ctypes.c_uint32),
        ("end_date_idx", ctypes.c_uint32),
        ("lookback_idx", ctypes.c_uint32),
        ("ema_idx", ctypes.c_uint32),
        ("top_n", ctypes.c_uint32),
        ("exit_buffer_rank", ctypes.c_uint32),
        ("max_per_sector", ctypes.c_uint32),
        ("sizing_mode", ctypes.c_uint32),
        ("filter_flags", ctypes.c_uint32),
        ("retrace_threshold", ctypes.c_float),
        ("initial_capital", ctypes.c_float),
        ("friction_bps", ctypes.c_float),
        ("slippage_bps", ctypes.c_float),
        ("risk_per_trade_pct", ctypes.c_float),
    ]


# 192-byte Tensor Cube Specification matching C99 TensorCube
class CTensorCube(ctypes.Structure):
    _fields_ = [
        ("num_dates", ctypes.c_uint32),
        ("num_symbols", ctypes.c_uint32),
        ("num_lookbacks", ctypes.c_uint32),
        ("num_ema_spans", ctypes.c_uint32),
        ("num_schedules", ctypes.c_uint32),
        ("reserved_align", ctypes.c_uint32),
        ("schedule_offsets", ctypes.c_uint32 * 8),
        ("schedule_lengths", ctypes.c_uint32 * 8),
        ("rebalance_indices", ctypes.c_void_p),
        ("benchmark_regime", ctypes.c_void_p),
        ("sector_ids", ctypes.c_void_p),
        ("open_px", ctypes.c_void_p),
        ("close_px", ctypes.c_void_p),
        ("atr_14", ctypes.c_void_p),
        ("volar_cubes", ctypes.c_void_p),
        ("res_mom_cubes", ctypes.c_void_p),
        ("high_cubes", ctypes.c_void_p),
        ("ema_cubes", ctypes.c_void_p),
        ("rs_pass_cubes", ctypes.c_void_p),
        ("vol_target_scalar", ctypes.c_void_p),
        ("delivery_veto_plane", ctypes.c_void_p),
    ]


NUMPY_SUMMARY_DTYPE = np.dtype(
    [
        ("param_id", np.uint32),
        ("cagr", np.float32),
        ("sharpe", np.float32),
        ("sortino", np.float32),
        ("max_drawdown", np.float32),
        ("calmar", np.float32),
        ("win_rate", np.float32),
        ("profit_factor", np.float32),
        ("ending_equity", np.float32),
        ("total_trades", np.uint32),
        ("winning_trades", np.uint32),
        ("turnover_annual", np.float32),
    ],
    align=True,
)


def compile_native_kernel(force_recompile: bool = False, target_path: Optional[Path] = None) -> Path:
    """Compiles sim_kernel.c with maximum architecture optimization (ARM64 NEON or x86_64 AVX2/native)."""
    so_target = target_path or get_so_target_path()
    if so_target.exists() and not force_recompile:
        src_mtime = C_SOURCE.stat().st_mtime
        so_mtime = so_target.stat().st_mtime
        if so_mtime >= src_mtime:
            return so_target

    machine = platform.machine().lower()
    if machine in ("aarch64", "arm64", "armv8l"):
        arch_flags = ["-march=armv8.2-a+fp16"]
    elif machine in ("x86_64", "amd64"):
        arch_flags = ["-march=native", "-mavx2", "-mfma"]
    else:
        arch_flags = ["-O3"]

    gcc_bin = get_compiler_bin()

    compile_cmd = [
        gcc_bin,
        "-O3",
        *arch_flags,
        "-ffast-math",
        "-fPIC",
        "-shared",
        "-pthread",
        str(C_SOURCE),
        "-o",
        str(so_target),
        "-lm",
    ]
    res = subprocess.run(compile_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        # Fallback to generic -O3 if machine specific flags fail
        compile_cmd_fallback = [
            gcc_bin,
            "-O3",
            "-ffast-math",
            "-fPIC",
            "-shared",
            "-pthread",
            str(C_SOURCE),
            "-o",
            str(so_target),
            "-lm",
        ]
        res = subprocess.run(compile_cmd_fallback, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"GCC Compilation Failed ({gcc_bin} -> {so_target}):\n{res.stderr}")
    print(f"[Bridge] Compiled native kernel ({machine}): {so_target} ({so_target.stat().st_size} bytes)")
    return so_target


class NativeBruteForceEngine:
    def __init__(self, force_recompile: bool = False):
        so_path = compile_native_kernel(force_recompile=force_recompile)
        self.lib = ctypes.CDLL(str(so_path))
        self.lib.run_parallel_brute_force.argtypes = [
            ctypes.POINTER(CSimParams),
            ctypes.POINTER(CSimulationSummary),
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(CTensorCube),
        ]
        self.lib.run_parallel_brute_force.restype = None

    def execute_sweep(
        self,
        params_list: List[Dict[str, Any]],
        cube,
        num_threads: int = 8,
    ) -> np.ndarray:
        """
        Executes parameter sweep across all configurations in parallel.
        Releases the Python GIL during the entire execution.
        """
        total = len(params_list)
        if total == 0:
            return np.empty(0, dtype=NUMPY_SUMMARY_DTYPE)

        c_params = (CSimParams * total)()
        for i, p in enumerate(params_list):
            c_params[i].param_id = int(p.get("param_id", i))
            c_params[i].schedule_idx = int(p.get("schedule_idx", SCHEDULE_MONTHLY))
            c_params[i].start_date_idx = int(p.get("start_date_idx", 0))
            c_params[i].end_date_idx = int(p.get("end_date_idx", 0))
            # Dynamic resolution of lookback and EMA indices matching cube dimensions
            max_lb_idx = max(0, len(getattr(cube, "lookback_values", [])) - 1)
            max_ema_idx = max(0, len(getattr(cube, "ema_span_values", [])) - 1)

            if "lookback" in p and hasattr(cube, "lookback_values") and p["lookback"] in cube.lookback_values:
                c_params[i].lookback_idx = int(cube.lookback_values.index(p["lookback"]))
            elif "lookback_idx" in p:
                c_params[i].lookback_idx = min(max_lb_idx, max(0, int(p["lookback_idx"])))
            elif hasattr(cube, "lookback_values") and 252 in cube.lookback_values:
                c_params[i].lookback_idx = int(cube.lookback_values.index(252))
            else:
                c_params[i].lookback_idx = min(max_lb_idx, max(0, int(p.get("lookback_idx", 2))))

            if "ema_trend" in p and hasattr(cube, "ema_span_values") and p["ema_trend"] in cube.ema_span_values:
                c_params[i].ema_idx = int(cube.ema_span_values.index(p["ema_trend"]))
            elif "ema_idx" in p:
                c_params[i].ema_idx = min(max_ema_idx, max(0, int(p["ema_idx"])))
            elif hasattr(cube, "ema_span_values") and 200 in cube.ema_span_values:
                c_params[i].ema_idx = int(cube.ema_span_values.index(200))
            else:
                c_params[i].ema_idx = min(max_ema_idx, max(0, int(p.get("ema_idx", 3))))
            c_params[i].top_n = int(p.get("top_n", 20))
            c_params[i].exit_buffer_rank = int(p.get("exit_buffer_rank", 40))
            c_params[i].max_per_sector = int(p.get("max_per_sector", 2))
            c_params[i].sizing_mode = 0 if p.get("sizing_mode", "atr_risk_parity") == "atr_risk_parity" else 1

            # Determine filter flags
            flags = p.get("filter_flags")
            if flags is None:
                # Build dynamically from booleans if provided
                flags = 0
                if p.get("use_retrace", True):
                    flags |= FILTER_RETRACE
                if p.get("use_trend", True):
                    flags |= FILTER_TREND
                if p.get("use_rs", True):
                    flags |= FILTER_RS
                if p.get("use_regime", True):
                    flags |= FILTER_REGIME
                if p.get("use_sector_cap", True):
                    flags |= FILTER_SECTOR_CAP
                if p.get("use_residual_mom", False):
                    flags |= FILTER_RESIDUAL_MOM
                if p.get("use_vol_targeting", False):
                    flags |= FILTER_VOL_TARGETING
                if p.get("use_delivery_veto", False):
                    flags |= FILTER_DELIVERY_VETO
            c_params[i].filter_flags = int(flags)

            c_params[i].retrace_threshold = float(p.get("retrace_threshold", 0.80))
            c_params[i].initial_capital = float(p.get("initial_capital", 1_000_000.0))
            c_params[i].friction_bps = float(p.get("friction_bps", 15.0))
            c_params[i].slippage_bps = float(p.get("slippage_bps", 5.0))
            c_params[i].risk_per_trade_pct = float(p.get("risk_per_trade_pct", 1.0))

        c_results = (CSimulationSummary * total)()

        # Build ctypes CTensorCube
        c_cube = CTensorCube()
        if cube.num_symbols > 2048:
            raise ValueError(
                f"Universe size {cube.num_symbols} exceeds native C kernel limit of 2048 symbols."
            )
        c_cube.num_dates = cube.num_dates
        c_cube.num_symbols = cube.num_symbols
        c_cube.num_lookbacks = len(cube.lookback_values)
        c_cube.num_ema_spans = len(cube.ema_span_values)
        c_cube.num_schedules = getattr(cube, "num_schedules", 1)
        c_cube.reserved_align = 0

        # Offsets and lengths
        for s in range(8):
            if s < c_cube.num_schedules:
                c_cube.schedule_offsets[s] = int(cube.schedule_offsets[s])
                c_cube.schedule_lengths[s] = int(cube.schedule_lengths[s])
            else:
                c_cube.schedule_offsets[s] = 0
                c_cube.schedule_lengths[s] = 0

        c_cube.rebalance_indices = cube.rebalance_indices.ctypes.data
        c_cube.benchmark_regime = cube.benchmark_regime.ctypes.data
        c_cube.sector_ids = cube.sector_ids.ctypes.data
        c_cube.open_px = cube.open_px.ctypes.data
        c_cube.close_px = cube.close_px.ctypes.data
        c_cube.atr_14 = cube.atr_14.ctypes.data
        c_cube.volar_cubes = cube.volar_cubes.ctypes.data
        c_cube.res_mom_cubes = cube.res_mom_cubes.ctypes.data if hasattr(cube, "res_mom_cubes") and cube.res_mom_cubes is not None else cube.volar_cubes.ctypes.data
        c_cube.high_cubes = cube.high_cubes.ctypes.data
        c_cube.ema_cubes = cube.ema_cubes.ctypes.data
        c_cube.rs_pass_cubes = cube.rs_pass_cubes.ctypes.data
        c_cube.vol_target_scalar = cube.vol_target_scalar.ctypes.data if hasattr(cube, "vol_target_scalar") and cube.vol_target_scalar is not None else 0
        c_cube.delivery_veto_plane = cube.delivery_veto_plane.ctypes.data if hasattr(cube, "delivery_veto_plane") and cube.delivery_veto_plane is not None else 0

        # Execute parallel C99 simulation
        self.lib.run_parallel_brute_force(
            c_params,
            c_results,
            ctypes.c_uint32(total),
            ctypes.c_uint32(num_threads),
            ctypes.byref(c_cube),
        )

        # Zero-copy memory view
        raw_arr = np.ctypeslib.as_array(c_results, shape=(total,)).view(dtype=NUMPY_SUMMARY_DTYPE)
        return raw_arr.copy()
