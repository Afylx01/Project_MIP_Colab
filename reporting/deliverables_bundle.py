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
from typing import Optional, List

logger = logging.getLogger("DeliverablesBundle")


def package_institutional_bundle(
    as_of_date: str,
    universe: str = "NIFTY750",
    base_dir: Optional[Path] = None,
    output_zip_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Assembles and compresses institutional artifacts into a production archive.
    """
    repo_root = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    reports_dir = repo_root / "reports"
    deliverables_dir = reports_dir / "deliverables"
    deliverables_dir.mkdir(parents=True, exist_ok=True)

    if output_zip_path is None:
        clean_univ = universe.replace(" ", "").upper()
        output_zip_path = deliverables_dir / f"MIP_Institutional_Bundle_{as_of_date}_{clean_univ}.zip"
    else:
        output_zip_path = Path(output_zip_path)

    # Candidate files to include
    files_to_pack: List[Tuple[Path, str]] = []

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
        return output_zip_path
    except Exception as e:
        logger.error(f"Failed to create bundle zip {output_zip_path}: {e}")
        return None
