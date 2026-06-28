<div align="center">

# 📚 OpenShelf

**Enumerate and batch-export the ebooks you purchased on Google Play Books**

DRM-free books → EPUB / PDF · DRM books → the official `.acsm` for Adobe Digital Editions · un-exportable ones are only recorded

[English](README.en.md) ｜ [**繁體中文**](README.md)

[![CI](https://github.com/SanHsien/openshelf/actions/workflows/ci.yml/badge.svg)](https://github.com/SanHsien/openshelf/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

</div>

---

> [!IMPORTANT]
> **This tool only does lawful exporting — it never breaks any protection.**
> An `.acsm` is just a fulfillment token; it does not contain the book's content. Adobe Digital Editions (ADE) is what downloads the book, binds it to your Adobe ID, and manages the DRM — the book stays encrypted throughout. OpenShelf does only two things with an `.acsm`: **download it** and **store it as-is**.
> **No ACSM parsing, no fulfilling outside ADE, no key extraction, no protection removal.** If what you want is "DRM stripping", this tool does not do it.

## ✨ Features

- 🔎 **One-click enumeration** of your whole Google Play Books library, auto-classifying each book's export status.
- 📥 **Three-way routing**: DRM-free → EPUB/PDF, DRM → official `.acsm`, un-exportable → record only.
- 🔐 **Never touches your credentials**: you sign in once in a real browser; the program only reuses the saved session.
- 🌐 **HTTP-first**: enumeration and downloads go through `httpx` backend endpoints, not fragile page DOM.
- 🧾 **manifest as the single source of truth**: resume, skip already-downloaded, produce reports.
- 🖥️ **Desktop GUI** with search, covers, a download queue with ETA, CSV/HTML export, and English/Chinese UI.

## 🖼️ Screenshot

![OpenShelf main window](docs/screenshots/main-window.png)

> The screenshot uses demo data only. It does not include a real Google account, library, or downloaded content.

## 🧱 Boundary & disclaimer

| Does ✅ | Does not ❌ |
|---|---|
| Download the official export files of books you own | Parse `.acsm` content |
| Save DRM-free books as EPUB/PDF | Fulfill outside ADE / extract the EPUB |
| Download the `.acsm` and store it as-is for ADE | Extract Adobe ADEPT keys |
| Classify, record, and skip un-exportable books | Remove or break any DRM/protection |

> Automating a signed-in Google service may conflict with its Terms of Service; assess and accept that risk yourself. This tool is only for exporting books **you lawfully own**.

## 🧭 How it works

OpenShelf is **HTTP-first**: the browser is used **only for a one-time sign-in** (Google blocks scripted credential login, so manual sign-in is the most robust). After the session is saved locally, **enumeration and downloads call the same Play Books web-version backend endpoints via `httpx`**, not page DOM/button selectors.

| Library offers | Category | Action |
|---|---|---|
| EPUB / PDF | `drm_free` | Download the file, verify extension + size |
| ACSM only | `acsm` | Download the `.acsm`, store as-is |
| Nothing | `no_export` | Record only |
| Error | `failed` | Record the error, retry next time |

> **Endpoint isolation**: Play Books has no official "download a purchased book" API. Library enumeration uses the private `SyncUserLibrary` gRPC-Web RPC (authenticated with SAPISIDHASH); download URLs are embedded in the response. Everything that can change when Google updates is isolated in `openshelf/playbooks.py`.

## 🚀 Quick start

**Requirements**: Python 3.11+, and a desktop GUI environment for the first sign-in.

```bash
git clone https://github.com/SanHsien/openshelf.git
cd openshelf
pip install -e .
```

> The first sign-in prefers your local Chrome / Edge. Only if you need to fall back to Playwright's bundled Chromium do you run `playwright install chromium`.

```bash
openshelf login     # 1) open a browser, sign in once
openshelf scan      # 2) enumerate the library, build the manifest
openshelf export    # 3) download the exportable books
openshelf status    # 4) see the stats
```

## 🧩 Commands

| Command | Description |
|---|---|
| `openshelf login` | Open a browser to sign in once and save the session |
| `openshelf scan` | Enumerate and classify the library over HTTP, write the manifest |
| `openshelf export` | Download exportable books (EPUB/PDF or `.acsm`) |
| `openshelf status` | Show manifest stats and refresh the download report |
| `openshelf report` | Write reports to the output folder — `--format txt\|csv\|html\|all` |
| `openshelf doctor` | Endpoint health check: confirm Google's backend response shape still matches |
| `openshelf acsm-open` / `acsm-report` | Batch-open downloaded `.acsm` with the default app / write report |
| `openshelf ebook-open` / `ebook-report` | Open downloaded DRM-free EPUB/PDF (`--target ade\|default`) / write report |
| `openshelf calibre-import` / `calibre-report` | Import DRM-free EPUB/PDF into Calibre / write report |
| `openshelf ui` | Open the desktop GUI (needs `pip install -e '.[gui]'`) |

Common `export` flags: `--format pdf`, `--skip-acsm`, `--only`, `--limit`, `--refresh-acsm`, `--force-refresh-acsm`, `--skip-failed`.

> Calibre handoff only processes `drm_free` EPUB/PDF that exist; `.acsm` is never imported into Calibre and still needs ADE.

## 📖 Reading `.acsm` with ADE

A DRM book downloads as an `.acsm`, **not the book itself**. To read it (done on your own computer; the tool is not involved):

1. Install **Adobe Digital Editions 4.5** and authorize the machine with your Adobe ID.
2. Double-click the `.acsm` in `output/`, or run `openshelf acsm-open` to hand them off to the default app.
3. Read inside ADE. The book is protected by Adobe DRM and only opens on authorized ADE/devices.

If ADE shows `E_ADEPT_REQUEST_EXPIRED`, the `.acsm` fulfillment token has expired. Re-download the official `.acsm` first: in the desktop app, enable **Force re-fetch .acsm** and click Download; in the CLI, run `openshelf export --force-refresh-acsm`, then open the new `.acsm` with ADE.

## 📂 Output & manifest

- Ebooks and `.acsm` → `output/` (configurable in `config.toml`).
- `output/manifest.json` → per-book metadata and category; resume/skip are based on it.
- `output/下載報表.txt` → human-readable report highlighting **missing books** (failed, no-export) and stale `.acsm`.
- `output/書庫清單.csv` / `output/書庫報表.html` → spreadsheet- and browser-friendly exports (`openshelf report`).

> `output/`, `.profile/`, and `storage_state.json` are git-ignored and never committed.

## 🛣️ Roadmap

Completed: M1–M11 through **v1.0.2** (sign-in, endpoint discovery, classification, HTTP download, retries/verification, desktop GUI, PyInstaller packaging, handoffs/reports/CI, desktop UX, releases, endpoint self-diagnosis, integration tests, structured logs, and cross-platform CI builds). Windows release artifacts have been locally smoke-tested; macOS and Linux artifacts are CI-built only and have not been tested on those platforms. See the [Chinese README](README.md#️-開發路線) for the detailed roadmap.

**Never**: DRM circumvention/decryption/stripping, `.acsm` parsing, fulfilling outside ADE, key extraction.

## 📝 License

**[Apache License 2.0](LICENSE).** You may use, modify, and distribute (including commercially), provided you keep the copyright notice and the attribution in [`NOTICE`](NOTICE.md). Provided "AS IS" without warranty. Only for exporting books **you lawfully own** — no ACSM parsing, no key extraction, no protection removal.

| | |
|---|---|
| License | [Apache License 2.0](LICENSE) |
| Copyright | © 2026 SanHsien |
| Contact | sanhsien@pm.me |

---

<div align="center">
Only for exporting the ebooks you <b>lawfully own</b>. No ACSM parsing, no key extraction, no protection removal. Please respect copyright and each service's terms.
</div>
