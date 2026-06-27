# AGENTS.md

給 Codex 在本專案工作時的指引。

## 專案宗旨與邊界

OpenShelf 枚舉並批次匯出使用者在 Google Play 圖書購買的電子書，依每本書的可匯出狀態分流處理：

1. **無 DRM 書** → 直接下載 EPUB / PDF。
2. **DRM 書（提供 ACSM 領取）** → 下載官方 `.acsm` 領取憑證，**原樣存檔**，供使用者自行在 Adobe Digital Editions（ADE）開啟閱讀。
3. **無任何匯出選項的書** → 只記錄，不下載。

`.acsm` 只是一張 XML 領取憑證，本身不含書的內容；真正下載、授權、管理 DRM 的是 ADE，書全程保持加密。下載憑證交給 ADE 閱讀是 Adobe DRM 的**正常設計用途**，不是規避。

**硬性邊界（不可違反）**：

- 嚴禁加入任何 DRM **規避、解密、脫殼**，或 **ACSM 解析**、在 ADE 之外自行 fulfill、Adobe ADEPT／金鑰抽取相關的程式碼或相依套件。
- `.acsm` 只做兩件事：**下載**、**原樣存檔**。不解析其內容、不改寫、不轉換、不在 ADE 之外處理。
- 不移除、不破壞任何電子書的保護措施。
- 若需求往「解開保護／脫殼／抽金鑰／解析 ACSM」這個方向走，**停下來告知使用者，不要自行實作**。

## 技術

- Python；採 **HTTP-first**：
  - 瀏覽器（Playwright）**只負責一次性登入**（優先用本機真 Chrome／Edge，避免 Google 擋自動化），擷取登入態存成 `storage_state.json`。**不在程式碼中處理 Google 帳密**。
  - 枚舉書庫與下載都用 `httpx` 走 Play Books 後端（`SyncUserLibrary` RPC，以 SAPISIDHASH ＋ 網頁版公開 API key 認證；自動分頁）。端點集中隔離在 `playbooks.py`。
- `manifest.json` 為單一事實來源（續傳、跳過、報表皆依此）；另產出人可讀的 `下載報表.txt`。
- ACSM 交接只批次用系統預設程式開啟已下載的 `.acsm`；不解析、不改寫、不轉換。
- EPUB/PDF 交接只處理已下載的無 DRM EPUB/PDF，可選 Calibre 或 ADE；`.acsm` 不匯入 Calibre。
- 登入態目錄與 `output/`（含已下載的書、`.acsm`、報表）不可進版控（見 `.gitignore`）。

> SAPISIDHASH 只是複製網頁版的合法登入認證（取自己帳號的書庫與官方下載 URL），不屬於 DRM 規避。

## 分類詞彙（manifest 用）

- `drm_free` — 可直接下載 EPUB/PDF。
- `acsm` — 僅提供 ACSM 領取，已下載 `.acsm`，需以 ADE 開啟。
- `no_export` — 無任何匯出選項，只記錄。
- `failed` — 流程出錯，待重試。

## 開發原則

- 最小干預：不主動重構、不改命名風格、不引入新架構。
- 有更好的做法可提案，但等使用者確認後再執行。
- 以繁體中文回覆。
- 程式碼保持完整，不省略。

## 指令對照

- `login` / `scan` / `export` / `status` / `report` / `acsm-open` / `acsm-report` / `ebook-open` / `ebook-report` / `calibre-import` / `calibre-report` / `ui` → 見 README「指令」。
- 模組分工 → 見 README「專案結構」。
