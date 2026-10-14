#!/usr/bin/env python3
"""
Uploads universe.db directly to Google Drive 'MIP' folder via Service Account.
Uses Google Drive API v3 with resumable 10MB chunked upload.
"""

import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SA_KEY_PATH = Path("/storage/emulated/0/Project/GCP_SA.json")
DB_PATH = Path("/storage/emulated/0/Project/MIP_Android/data/universe.db")
TARGET_FOLDER_NAME = "MIP"
TARGET_FOLDER_ID = "1gbovGQ5k_kTQbTW2SAueLH3bAbToevag"


def upload_universe():
    if not SA_KEY_PATH.exists():
        print(f"❌ Service account key not found at: {SA_KEY_PATH}")
        sys.exit(1)

    if not DB_PATH.exists():
        print(f"❌ Database not found at: {DB_PATH}")
        sys.exit(1)

    db_size = DB_PATH.stat().st_size
    print(f"🚀 Starting Google Drive Upload:")
    print(f"  • Source Database: {DB_PATH} ({db_size / (1024*1024):.2f} MB)")
    print(f"  • Target Folder:   {TARGET_FOLDER_NAME} (ID: {TARGET_FOLDER_ID})")

    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = service_account.Credentials.from_service_account_file(str(SA_KEY_PATH), scopes=scopes)
    service = build("drive", "v3", credentials=creds)

    # Check if universe.db already exists inside the MIP folder
    existing = service.files().list(
        q=f"'{TARGET_FOLDER_ID}' in parents and name='universe.db' and trashed=false",
        fields="files(id, name, size)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute().get("files", [])

    file_metadata = {
        "name": "universe.db",
        "parents": [TARGET_FOLDER_ID] if not existing else None,
    }

    # 10MB chunked resumable upload
    media = MediaFileUpload(
        str(DB_PATH),
        mimetype="application/x-sqlite3",
        resumable=True,
        chunksize=10 * 1024 * 1024,
    )

    t0 = time.time()
    if existing:
        file_id = existing[0]["id"]
        print(f"  • Updating existing file in Google Drive (ID: {file_id})...")
        request = service.files().update(
            fileId=file_id,
            media_body=media,
            supportsAllDrives=True,
        )
    else:
        print(f"  • Creating new file in Google Drive 'MIP' folder...")
        request = service.files().create(
            body={"name": "universe.db", "parents": [TARGET_FOLDER_ID]},
            media_body=media,
            supportsAllDrives=True,
        )

    response = None
    last_pct = -1
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            if pct != last_pct:
                mb_done = (status.progress() * db_size) / (1024 * 1024)
                elapsed = time.time() - t0
                speed = mb_done / elapsed if elapsed > 0 else 0
                print(f"  ⏳ Upload Progress: {pct}% ({mb_done:.1f} / {db_size / (1024*1024):.1f} MB) @ {speed:.2f} MB/s")
                last_pct = pct

    elapsed = time.time() - t0
    final_id = response.get("id")
    print(f"\n✅ UPLOAD COMPLETE in {elapsed:.2f}s!")
    print(f"  • File Name:     {response.get('name')}")
    print(f"  • Google Drive ID: {final_id}")
    print(f"  • Stored In:     MIP folder (ID: {TARGET_FOLDER_ID})")

    # Record ID into environment / config for cloud sync if needed
    out_id_file = BASE_DIR / "data" / ".gdrive_file_id"
    out_id_file.parent.mkdir(parents=True, exist_ok=True)
    out_id_file.write_text(final_id, encoding="utf-8")
    print(f"  • Stored file ID reference in: {out_id_file}")


if __name__ == "__main__":
    upload_universe()
