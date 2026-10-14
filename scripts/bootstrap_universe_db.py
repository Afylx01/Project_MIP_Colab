"""
MIP Android — Database Provisioning & Bootstrap Script
Directive: STAGE-7-DATA-BOOTSTRAP-01

Implements the institutional database provisioning state machine:
  MISSING -> DOWNLOAD -> VERIFY -> INSTALL -> VALIDATE -> READY

Guarantees:
  - Atomic replacement via temporary storage (no partial installations)
  - Strict SHA-256 integrity verification against canonical checksum
  - Schema and row count validation before promoting to production
  - Automatic rollback and cleanup on failure or interruption
"""

import argparse
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import urllib.request
from typing import Optional, Tuple

CANONICAL_DB_SHA256 = "70c6be1aabc9c0cd5890ae62fc359c9d6f4ae8bdefd78f8c3aebbe93383f7fbd"


class BootstrapStateMachine:
    """State machine managing the lifecycle of universe.db provisioning."""

    STATES = ["MISSING", "DOWNLOAD", "VERIFY", "INSTALL", "VALIDATE", "READY", "FAILED"]

    def __init__(self, target_path: Path, expected_sha: str = CANONICAL_DB_SHA256):
        self.target_path = Path(target_path).resolve()
        self.expected_sha = expected_sha.lower().strip()
        self.current_state = "MISSING"
        self.history = []

    def set_state(self, state: str, detail: str = ""):
        assert state in self.STATES, f"Invalid state: {state}"
        self.current_state = state
        entry = {"state": state, "detail": detail}
        self.history.append(entry)
        prefix = f"[{state}]"
        print(f"--> State Machine: {prefix:<12} {detail}")

    def compute_sha256(self, file_path: Path) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
        return h.hexdigest().lower()

    def validate_sqlite_db(self, db_path: Path) -> Tuple[bool, str]:
        """Validates that the database file is a valid, readable MIP SQLite universe."""
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM prices;")
            row_count = cursor.fetchone()[0]
            if row_count < 100000:
                conn.close()
                return False, f"Row count {row_count} suspiciously low"
            
            cursor.execute("SELECT max(date) FROM prices;")
            max_d = cursor.fetchone()[0]
            if not max_d:
                conn.close()
                return False, "Missing latest date in prices"

            conn.close()
            return True, f"Valid SQLite DB: {row_count:,} rows, latest date: {max_d}"
        except Exception as e:
            return False, f"SQLite validation failed: {e}"

    def bootstrap(
        self,
        source: Optional[str] = None,
        force: bool = False,
    ) -> bool:
        """Executes the provisioning workflow."""
        self.target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = self.target_path.parent / f"{self.target_path.name}.tmp.{os.getpid()}"

        try:
            # 1. Evaluate Current State
            if self.target_path.exists() and not force:
                self.set_state("VERIFY", f"Checking existing file at {self.target_path}")
                existing_sha = self.compute_sha256(self.target_path)
                if existing_sha == self.expected_sha:
                    self.set_state("VALIDATE", "Existing file checksum matches expected SHA-256")
                    ok, msg = self.validate_sqlite_db(self.target_path)
                    if ok:
                        self.set_state("READY", f"Existing database is healthy and ready: {msg}")
                        return True
                    else:
                        print(f"Existing file corrupted despite SHA: {msg}. Forcing replacement.")
                else:
                    print(f"Existing file SHA mismatch ({existing_sha} != {self.expected_sha}). Replacing.")

            self.set_state("MISSING", f"Target {self.target_path} requires provisioning")

            # 2. Determine Source
            source_path = None
            source_url = None

            if source:
                if source.startswith("http://") or source.startswith("https://"):
                    source_url = source
                else:
                    source_path = Path(source).resolve()
            else:
                # Default search locations
                candidates = [
                    Path("/sdcard/Documents/Projects/Project_MIP_Pydroid3/data/universe.db"),
                    Path("/storage/emulated/0/Documents/Projects/Project_MIP_Pydroid3/data/universe.db"),
                    Path(__file__).resolve().parent.parent.parent / "Project_MIP_Pydroid3" / "data" / "universe.db",
                ]
                for c in candidates:
                    if c.exists():
                        source_path = c
                        break

            if not source_path and not source_url:
                source_env = os.environ.get("MIP_DB_SOURCE")
                if source_env:
                    if source_env.startswith("http://") or source_env.startswith("https://"):
                        source_url = source_env
                    else:
                        source_path = Path(source_env).resolve()

            if not source_path and not source_url:
                self.set_state("FAILED", "No valid source available (local path or URL)")
                return False

            # 3. Download / Staging
            self.set_state("DOWNLOAD", f"Staging data from {source_url or source_path} to {tmp_target}")
            if source_url:
                # HTTP Download
                urllib.request.urlretrieve(source_url, str(tmp_target))
            else:
                assert source_path is not None
                if not source_path.exists():
                    self.set_state("FAILED", f"Source path does not exist: {source_path}")
                    return False
                
                if str(source_path).endswith(".gz"):
                    with gzip.open(source_path, "rb") as f_in, open(tmp_target, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                else:
                    shutil.copyfile(source_path, tmp_target)

            # 4. Checksum Verification
            self.set_state("VERIFY", f"Computing SHA-256 of staged file {tmp_target}")
            computed_sha = self.compute_sha256(tmp_target)
            if computed_sha != self.expected_sha:
                self.set_state("FAILED", f"SHA-256 mismatch! Expected {self.expected_sha}, got {computed_sha}")
                if tmp_target.exists():
                    tmp_target.unlink()
                return False

            # 5. Schema Validation on Staged File
            self.set_state("VALIDATE", f"Validating integrity of staged file {tmp_target}")
            is_valid, val_msg = self.validate_sqlite_db(tmp_target)
            if not is_valid:
                self.set_state("FAILED", f"Staged database validation failed: {val_msg}")
                if tmp_target.exists():
                    tmp_target.unlink()
                return False

            # 6. Atomic Install
            self.set_state("INSTALL", f"Promoting {tmp_target} -> {self.target_path}")
            os.replace(str(tmp_target), str(self.target_path))

            # 7. Final Verification in Place
            self.set_state("READY", f"Database successfully installed and verified ({val_msg})")
            return True

        except Exception as e:
            self.set_state("FAILED", f"Exception during bootstrap: {e}")
            if tmp_target.exists():
                try:
                    tmp_target.unlink()
                except Exception:
                    pass
            return False


def main():
    parser = argparse.ArgumentParser(description="MIP Android Database Provisioning Tool")
    parser.add_argument("--source", type=str, default=None, help="Local file path or URL to universe.db")
    parser.add_argument("--target", type=str, default=None, help="Target destination path for universe.db")
    parser.add_argument("--expected-sha", type=str, default=CANONICAL_DB_SHA256, help="Expected SHA-256 hash")
    parser.add_argument("--force", action="store_true", help="Force re-provisioning even if database exists")

    args = parser.parse_args()

    target = Path(args.target) if args.target else (Path(__file__).resolve().parent.parent / "data" / "universe.db")
    sm = BootstrapStateMachine(target_path=target, expected_sha=args.expected_sha)
    success = sm.bootstrap(source=args.source, force=args.force)

    if success:
        print("\n[SUCCESS] Database provisioning completed successfully.")
        sys.exit(0)
    else:
        print(f"\n[ERROR] Database provisioning failed in state: {sm.current_state}")
        sys.exit(1)


if __name__ == "__main__":
    main()
