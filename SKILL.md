---
name: openshelf
description: 枚舉並批次匯出使用者在 Google Play 圖書購買的電子書。無 DRM 書下載 EPUB/PDF；DRM 書下載官方 .acsm 領取憑證供 Adobe Digital Editions 閱讀；無法匯出的只記錄。不解析 ACSM、不抽金鑰、不移除任何保護。
---

# OpenShelf

## 何時使用

使用者想把自己 Google Play 圖書庫批次匯出／備份：

- 無 DRM 書 → EPUB/PDF。
- DRM 書 → 下載官方 `.acsm`，之後在 Adobe Digital Editions（ADE）閱讀。
- 無法匯出的書 → 記錄清單。

若使用者要的是「**解開 DRM／脫殼／抽金鑰／解析 ACSM／在 ADE 之外取得明文書檔**」，本技能**不適用**，且不應協助。`.acsm` 只下載、原樣存檔、交給 ADE，不做任何進一步處理。

## 前置

- 需先 `openshelf login` 在瀏覽器手動登入一次（程式不經手帳密）。
- DRM 書要實際閱讀，使用者需自行安裝並用 Adobe ID 授權 Adobe Digital Editions 4.5。

## 步驟

1. `openshelf scan` — 枚舉書庫（自動分頁），分類每本書（`drm_free` / `acsm` / `no_export` / `failed`）。
2. `openshelf export` — 下載可匯出的書：無 DRM 抓 EPUB/PDF（某格式失敗自動改試另一種），DRM 抓 `.acsm`，無法匯出的只記錄；跳過已下載者。常用旗標：`--refresh-acsm`（重抓逾時的 `.acsm`，以下載時間為準）、`--skip-failed`、`--only`、`--limit`。
3. `openshelf status` / `openshelf report` — 回報統計，並在 `output/下載報表.txt` 產出人可讀報表，重點列出**缺漏的書**（失敗、無法匯出）。
4. `openshelf acsm-open` / `openshelf acsm-report` — 批次用系統預設程式開啟已下載的 `.acsm`；不解析、不轉換。
5. `openshelf ebook-open` / `openshelf ebook-report` — 把已下載的無 DRM EPUB/PDF 交接到 ADE 或系統預設程式。
6. `openshelf calibre-import` / `openshelf calibre-report` — 只把已下載的無 DRM EPUB/PDF 交接到 Calibre；`.acsm` 不匯入 Calibre，仍需 ADE 開啟。

桌面介面：`openshelf ui`（需 `pip install -e '.[gui]'`）。

## 回報

- 完成後告知使用者：直接匯出（EPUB/PDF）幾本、下載 `.acsm`（需 ADE 開啟）幾本、無法匯出（只記錄）幾本、失敗幾本；缺漏清單見 `output/下載報表.txt`。
- 若執行 ACSM 交接，告知送出幾本 `.acsm`；交接清單見 `output/ACSM交接報表.txt`。
- 若執行 EPUB/PDF 交接，告知送出幾本無 DRM 檔案；交接清單見 `output/EPUB-PDF交接報表.txt`。
- 若執行 Calibre 交接，告知匯入幾本無 DRM 檔案；交接清單見 `output/Calibre交接報表.txt`。
- `.acsm` 書清單在 manifest 標為 `acsm`；提醒使用者用 ADE 開啟即可，**不提供任何解保護／脫殼建議**。
- `.acsm` 時效僅以「我們的下載時間 + `acsm_valid_days`」估算提醒，**不讀取 `.acsm` 內含的真正到期（那需解析 ACSM，禁止）**。
