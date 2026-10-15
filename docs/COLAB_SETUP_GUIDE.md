# Google Colab Setup & Zero-Leak Cloud Staging Guide
**Project MIP (Momentum Investing Platform) • Cloud & Mobile Architecture**

---

## 1. Quick Start: One-Click Execution

1. Open [`notebooks/Project_MIP_Colab.ipynb`](file:///storage/emulated/0/Project/Project_MIP_Colab/notebooks/Project_MIP_Colab.ipynb) in Google Colab.
2. Click **Runtime > Run all** (or execute Cells 1 through 5 sequentially).
3. The interactive dashboard allows you to select any of the 36 official NIFTY universes, adjust portfolio sizing, and execute momentum scans or brute force simulations.

---

## 2. Zero-Leak Google Drive Access via Service Account

### The Challenge
You want Google Colab to access `universe.db` (351 MB) from your Google Drive, but you want your GitHub repository and shared notebooks to be **100% public and shareable without exposing your private Service Account `.json` file or credentials**.

### Solution: Google Colab Secrets Vault (Zero Leaks)
Google Colab provides a native **Secrets Manager** that stores sensitive tokens encrypted in your personal Google account. Secrets are **never** visible to anyone viewing your shared notebook or code.

#### Step 1: Share Google Drive Folder with the Service Account
Because Google Cloud Service Accounts do not have their own Google Drive storage quota (0 GB quota), you must grant the service account access to your Drive folder:
1. Open Google Drive in your browser.
2. Create or navigate to the folder containing `universe.db` (e.g. `MIP/`).
3. Right-click the folder and select **Share**.
4. In the "Add people and groups" field, paste your Service Account email:
   ```text
   mip1-890@mip1-scanner.iam.gserviceaccount.com
   ```
5. Set permission to **Editor** (or **Viewer**) and click **Send / Share**.

#### Step 2: Add Service Account JSON to Colab Secrets
1. In Google Colab, click the **Key icon** (🔑 *Secrets*) on the left sidebar.
2. Click **+ Add new secret**.
3. Name: `GDRIVE_SA_KEY`
4. Value: Open your `.json` service account file on your computer/phone, copy the **entire JSON text**, and paste it into the Value box.
5. Toggle **Notebook access** to ON for this notebook.

#### Step 3: Run the Notebook!
The notebook automatically calls:
```python
from google.colab import userdata
sa_key_json = userdata.get('GDRIVE_SA_KEY')
```
Your code accesses the key securely from memory. **No `.json` file is ever saved in the repository, and no credentials appear in git commits or cell outputs!**

---

## 3. Alternative: Interactive Google Drive Mount (No JSON Required)
If you prefer not using service accounts at all:
1. Run Cell 2 in the notebook.
2. Colab will display a prompt: *"Permit this notebook to access your Google Drive files?"*
3. Click **Connect to Google Drive**.
4. Colab mounts your drive at `/content/drive/MyDrive/`.
5. The staging engine automatically finds `/content/drive/MyDrive/MIP/universe.db` and copies it to local NVMe in 3 seconds!

---

## 4. Zero-Friction Option: Direct Public Google Drive Mirror (Zero-Setup)
If you don't have Google Drive or a Service Account configured:
1. The notebook automatically falls back to downloading the verified pre-compiled `universe.db` (351 MB) directly from our public Google Drive mirror.
2. Direct link: [Google Drive universe.db](https://drive.google.com/file/d/1mnaMfODbDwcdyG5NyQrLCunWKwYir1aT/view?usp=sharing)
3. You can also download it manually via terminal:
   ```bash
   gdown --id 1mnaMfODbDwcdyG5NyQrLCunWKwYir1aT -O data/universe.db
   ```

---

## 5. Why We Stage `universe.db` to Local NVMe (The 40x Latency Law)
Google Colab's `/content/drive/` is mounted using Google Drive FUSE (Filesystem in Userspace).
- SQLite performs 4 KB random page reads and B-tree binary seeks.
- Over FUSE, every page seek requires an HTTP round-trip over the network.
- Query latency on FUSE: **50–150 ms per query** (a full scan takes 3–4 minutes).
- When staged to local Colab NVMe (`/content/Project_MIP_Colab/data/universe.db`): **0.08–0.4 ms per query** (scan completes in 0.8 seconds).

`core/cloud_sync.py` automatically performs this staging transparently.

---

## 6. Sharing the Codebase Safely
When sharing this repository on GitHub or with colleagues:
- `.gitignore` strictly ignores:
  - `*.env`
  - `*service_account*.json`
  - `*.json` with private keys
  - `data/universe.db` (351 MB)
  - `*.so` compiled objects
  - `reports/*.xlsx` and private outputs
- Anyone who clones the repo only needs to stage `universe.db` (either via Drive mount, service account secret, or manual copy), and they can run immediately without having your personal keys!
