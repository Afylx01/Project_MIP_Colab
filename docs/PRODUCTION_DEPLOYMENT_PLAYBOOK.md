# PROJECT MIP — PRODUCTION DEPLOYMENT & OPERATIONAL PLAYBOOK

**Document Version**: 1.0.0 (Production Sealed)  
**Governance Protocol**: STRICT TDD / INVARIANT FIREWALL / HEADLESS PRODUCTION READINESS  
**Target Architecture**: Ubuntu Linux (ARM64 / x86_64), Android Termux / Pydroid Environments  

---

## 1. SYSTEM PREREQUISITES & HARDWARE REQUIREMENTS

Before deploying Project MIP in an unattended production environment, verify the following prerequisites:

| Requirement | Minimum Specification | Recommended Specification |
| :--- | :--- | :--- |
| **Operating System** | Linux (Ubuntu 22.04+, Debian 12+, Android Linux Kernel 5.10+) | Ubuntu Linux 24.04 LTS or 26.04 LTS (ARM64) |
| **Python Runtime** | Python 3.11+ | Python 3.12, 3.13, or 3.14 |
| **SQLite3 Engine** | SQLite 3.35.0+ | SQLite 3.45.0+ with WAL mode enabled |
| **RAM Footprint** | 1.0 GB Free RAM | 2.0 GB+ RAM (Peak RSS under full NIFTY 750 scan: ~700 MB) |
| **Disk Storage** | 1.5 GB Free Disk Space | 3.0 GB+ Free Disk Space (DB: 352 MB, Logs capped: 50 MB, Reports: ~20 MB/month) |
| **Core Dependencies**| `pandas`, `openpyxl`, `sqlite3` (built-in) | Native zero-compiler pure Python standard library |

---

## 2. ENVIRONMENT SETUP & CONFIGURATION

### A. Repository Path Configuration
All production execution commands assume the repository root is located at:
```bash
export MIP_HOME="/mnt/sdcard/Project/MIP_Android"
# (or local path: /storage/emulated/0/Project/MIP_Android)
cd "$MIP_HOME"
```

### B. Telegram Notification Dispatcher (Optional / Fail-Safe)
If automated Telegram digests and critical health alerts are desired, set the following environment variables:
```bash
export TELEGRAM_BOT_TOKEN="<your_bot_token>"
export TELEGRAM_CHAT_ID="<your_chat_id>"
```
> [!NOTE]
> If credentials are unset or network connectivity is offline, the pipeline fails safe without halting: the scan completes normally, and dispatch audit records are preserved in `reports/alert_dispatch.json` with status `SKIPPED_UNCONFIGURED` or `OFFLINE_FAILED`.

### C. Production Database Immutability Firewall
The canonical SQLite database (`data/universe.db`) is strictly protected against accidental runtime mutation. Any attempt to acquire a write connection or execute write transactions on `universe.db` without `MIP_ALLOW_PROD_MUTATION=1` will raise an immediate `PermissionError`.
```bash
# Production runs must NEVER set MIP_ALLOW_PROD_MUTATION=1
# Read-only scans enforce the immutability invariant automatically.
```

---

## 3. UNATTENDED DAILY EOD SCHEDULING (18:30 IST)

The National Stock Exchange (NSE) cash market closes at 15:30 IST. Official Bhavcopy files and trade records are published between 17:30 and 18:15 IST. Project MIP triggers at **18:30 IST (13:00 UTC)** on official trading days.

### Option 1: Calendar-Aware Crontab Daemon Step (Recommended)
This mode invokes the calendar-aware runner (`schedule_production_cron.py --once`). If executed on an NSE exchange holiday (e.g., Republic Day, Diwali) or weekend, it logs standing-by status and exits cleanly (exit code 0) without executing redundant historical scans.

1. **Inspect Crontab Configuration**:
   ```bash
   python3 scripts/schedule_production_cron.py --print-crontab --mode daemon_step
   ```
2. **Standard Crontab Line**:
   ```crontab
   # Project MIP Unattended EOD Momentum Scanner (Calendar-Aware Daemon Step: 18:30 IST Weekdays)
   30 18 * * 1-5 cd /mnt/sdcard/Project/MIP_Android && /usr/bin/python3 /mnt/sdcard/Project/MIP_Android/scripts/schedule_production_cron.py --once >> /mnt/sdcard/Project/MIP_Android/logs/scheduler_daemon.log 2>&1
   ```
3. **Automated Crontab Installation**:
   ```bash
   (crontab -l 2>/dev/null; python3 scripts/schedule_production_cron.py --print-crontab --mode daemon_step) | crontab -
   ```

### Option 2: Direct Headless Production Pipeline
Direct invocation of `run_production_pipeline.py`. Runs full pre-flight health checks, scan calculations, deliverable serialization, and alert dispatching:
```crontab
# Project MIP Unattended EOD Production Momentum Scanner (Direct Pipeline: 18:30 IST Weekdays)
30 18 * * 1-5 cd /mnt/sdcard/Project/MIP_Android && /usr/bin/python3 /mnt/sdcard/Project/MIP_Android/scripts/run_production_pipeline.py >> /mnt/sdcard/Project/MIP_Android/logs/production_pipeline.log 2>&1
```

### Option 3: Headless Long-Running Polling Daemon (Non-Cron Environments)
For environments where `cron` is not installed or available (e.g. Android Termux without cron service, Pydroid, Docker containers):
```bash
nohup python3 scripts/schedule_production_cron.py --daemon --poll-interval 60 >> logs/scheduler_daemon.log 2>&1 &
```
The daemon continuously sleeps until 18:30 IST on the next official NSE trading day, executes the scan pipeline, and resumes sleeping.

---

## 4. LOG ROTATION & STORAGE CAPACITY SAFEGUARDS

To protect mobile ARM64 internal storage and embedded disks against disk exhaustion:
- All scheduler loggers utilize Python's `RotatingFileHandler`.
- Log files are capped at **10 MB per file** with a maximum of **5 backup archives** (`scheduler_daemon.log.1`, etc.).
- Total maximum disk footprint across all logs is strictly capped at **50 MB**.
- Primary logs:
  - `logs/scheduler_daemon.log`: Scheduler polling and trading session evaluation events.
  - `logs/production_pipeline.log`: Full scan execution stdout/stderr and audit trails.

---

## 5. PRODUCTION DELIVERABLES & ARTIFACT DIRECTORY

Every successful scan run generates the following deliverables under `reports/`:

| Deliverable Artifact | Format | Description |
| :--- | :--- | :--- |
| `reports/MIP_Institutional_Scan_*.xlsx` | Excel Workbook | 14-sheet institutional tearsheet with embedded charts and metrics. |
| `reports/screener_output_live.csv` | CSV | Top momentum candidates (Tier-1 Buys + Buffer Holds) with Volar scores. |
| `reports/market_breadth.json` | JSON | Advance/decline ratios, regime state (`BULL`, `NEUTRAL`, `BEAR`). |
| `reports/sector_rotation.json` | JSON | 22 AMFI macro sector relative strength rankings and momentum trends. |
| `reports/operational_health.json` | JSON | 7 fail-closed pre-flight health check results. |
| `reports/pipeline_telemetry.json` | JSON | Full runtime telemetry, memory RSS, sector cap compliance, and deliverables map. |
| `reports/alert_dispatch.json` | JSON | Audit log of Telegram alert dispatch (payload length, timestamp, delivery status). |

---

## 6. INCIDENT TRIAGE & TROUBLESHOOTING

### Incident 1: Pre-Flight Operational Health Failure
- **Symptom**: Pipeline aborts with `RuntimeError: Pre-flight health check failed` and dispatches `🚨 CRITICAL OPERATIONAL ALERT`.
- **Action**:
  1. Inspect `reports/operational_health.json`.
  2. Identify the failed check (e.g. database file permissions, corporate actions hash mismatch, strategy fingerprint change).
  3. Verify file integrity: `sha256sum data/universe.db data/corporate_actions_registry.json data/trading_calendar.txt`.

### Incident 2: Lock Collision (`LockAcquisitionError`)
- **Symptom**: Pipeline exits with exit code 2 and message `Lock collision: Active pipeline lock held by PID <pid>`.
- **Cause**: A previous scan is still running or another process acquired `.scanner.lock`.
- **Automatic Recovery**: The lock manager automatically checks process liveness (`os.kill(pid, 0)`). If the PID is dead, it reclaims the lock cleanly. Stale locks expire automatically after 1,800 seconds (30 minutes).
- **Manual Override**: If an unrecoverable hung process was SIGKILLed, remove `.scanner.lock`:
  ```bash
  rm -f /mnt/sdcard/Project/MIP_Android/.scanner.lock
  ```

### Incident 3: Telegram Alert Network Timeout
- **Symptom**: Telemetry records `"alert_dispatch_status": "OFFLINE_FAILED"` or `"EXCEPTION"`.
- **Impact**: Zero impact on scan results. Deliverables are fully serialized on disk. Check internet connectivity and Telegram bot token validity.

---

## 7. OPERATIONAL READINESS VERIFICATION

Run the standalone readiness verification script prior to going live:
```bash
python3 scripts/verify_production_readiness.py
```
Expected output:
```text
======================================================================
           PROJECT MIP — PRODUCTION READINESS VERIFICATION
======================================================================
  [PASS] Operational Health Checks: 7/7 safeguards healthy
  [PASS] Database Integrity: universe.db (2,164,420 rows, integrity ok)
  [PASS] Directory Permissions: reports/ and logs/ writable
  [PASS] Crontab Paths: executable and script paths valid
  [PASS] Strategy Fingerprint: 9036fae5c41a27713901c8e82a97dfa07bc2f26a86f8e3231fdb8868d78673de
  [PASS] Architectural Invariant: Exactly 25 core modules tracked
----------------------------------------------------------------------
STATUS: PRODUCTION_READY: TRUE
======================================================================
```
