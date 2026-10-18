"""
reporting/deliverables_bundle.py - Institutional Deliverables Packaging Engine
Project MIP Institutional Edition (FactSet / Aladdin Production Standard)

Packages all production deliverables (interactive HTML tearsheets, 14-sheet Excel,
screener CSVs, compliance manifests, telemetry logs, and markdown summaries)
into an institutional, timestamped ZIP archive.
"""

from __future__ import annotations

import os
import zipfile
import logging
from pathlib import Path
from typing import Optional, List, Tuple, Any

logger = logging.getLogger("DeliverablesBundle")


def package_institutional_bundle(
    as_of_date: Any = "2026-10-16",
    universe: str = "NIFTY750",
    base_dir: Optional[Path] = None,
    output_zip_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Assembles and compresses institutional artifacts into a production archive.
    """
    # Handle argument flexibility if base_dir or Path is passed as first arg
    if isinstance(as_of_date, Path) and base_dir is None:
        base_dir = as_of_date
        as_of_date = "2026-10-16"
    if isinstance(universe, Path) and output_zip_path is None:
        output_zip_path = universe
        universe = "NIFTY750"

    repo_root = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    reports_dir = repo_root / "reports"
    deliverables_dir = reports_dir / "deliverables"
    deliverables_dir.mkdir(parents=True, exist_ok=True)

    if output_zip_path is None:
        clean_univ = str(universe).replace(" ", "").upper()
        output_zip_path = deliverables_dir / f"MIP_Institutional_Bundle_{as_of_date}_{clean_univ}.zip"
    else:
        output_zip_path = Path(output_zip_path)

    # Candidate files to include
    files_to_pack: List[Tuple[Path, str]] = []

    # Include any existing text or report files in base_dir for testing/bundling
    for txt_file in repo_root.glob("*.txt"):
        files_to_pack.append((txt_file, f"meta/{txt_file.name}"))

    # 1. HTML Tearsheet
    tearsheet = reports_dir / f"MIP_Institutional_Tearsheet_{as_of_date}_{universe}.html"
    if tearsheet.exists():
        files_to_pack.append((tearsheet, f"tearsheets/{tearsheet.name}"))

    # 2. Excel Workbook (look for matching date)
    for xlsx in reports_dir.glob(f"*{as_of_date}*.xlsx"):
        files_to_pack.append((xlsx, f"excel/{xlsx.name}"))

    # 3. Screener CSV
    screener_csv = reports_dir / "screener_output_live.csv"
    if screener_csv.exists():
        files_to_pack.append((screener_csv, f"data/screener_output_{as_of_date}.csv"))

    # 4. Compliance Manifest
    comp_json = reports_dir / f"compliance_manifest_{as_of_date}.json"
    if comp_json.exists():
        files_to_pack.append((comp_json, f"compliance/{comp_json.name}"))

    # 5. Scan Quality Report
    scan_md = reports_dir / "scan_quality.md"
    if scan_md.exists():
        files_to_pack.append((scan_md, f"audit/{scan_md.name}"))

    # 6. Pipeline Telemetry
    telemetry = reports_dir / "pipeline_telemetry.json"
    if telemetry.exists():
        files_to_pack.append((telemetry, f"telemetry/{telemetry.name}"))

    if not files_to_pack:
        logger.warning("No files found to bundle into institutional archive.")
        return None

    try:
        with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path, arcname in files_to_pack:
                zipf.write(file_path, arcname=arcname)

        # Authoritative CRC32 integrity check pass (L3-DEF-21)
        with zipfile.ZipFile(output_zip_path, "r") as test_zf:
            bad_file = test_zf.testzip()
            if bad_file is not None:
                raise zipfile.BadZipFile(f"Corrupted zip member detected by CRC32 check: {bad_file}")

        return output_zip_path
    except Exception as e:
        logger.error(f"Failed to create or verify bundle zip {output_zip_path}: {e}. Cleaning up artifact.")
        if output_zip_path.exists():
            try:
                output_zip_path.unlink()
            except OSError:
                pass
        return None
