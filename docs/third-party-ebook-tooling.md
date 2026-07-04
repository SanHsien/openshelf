# 第三方電子書工具與 OpenShelf 邊界

這份文件整理常見的 Google Play 圖書匯出工具、Adobe Digital Editions
與 Calibre 的角色，供之後閱讀本 repo 的人快速理解背景與專案取捨。

## 核心觀念

Google Play 圖書的匯出結果大致分成三種：

| 類型 | 常見檔案 | OpenShelf 的處理 |
|---|---|---|
| 無 DRM 書 | `.epub` / `.pdf` | 直接下載、覆核檔案、可交接 Calibre |
| DRM 書 | `.acsm` | 下載官方領取憑證，原樣存檔，交給 ADE |
| 無匯出選項 | 無 | 只記錄於 manifest / 報表 |

`.acsm` 不是電子書本體，而是 Adobe Digital Editions 使用的領取憑證。
ADE 會依憑證下載並授權對應書籍。這個流程仍維持出版商設定的 DRM 保護，
不是產生可任意閱讀器開啟的無保護檔案。

## Adobe Digital Editions 的角色

Adobe Digital Editions，簡稱 ADE，是官方閱讀與授權工具。

OpenShelf 對 `.acsm` 的定位：

- 下載官方 `.acsm`。
- 原樣存檔。
- 可批次用系統預設程式開啟，Windows 上通常會交給 ADE。
- 不解析、不改寫、不轉換 `.acsm`。

ADE 常見輸出位置是：

```text
C:\Users\<使用者名稱>\Documents\My Digital Editions
```

該資料夾中的檔案是否能在其他閱讀器開啟，取決於書籍本身授權與 DRM 狀態。
OpenShelf 不把 ADE 產物當成可自由轉換的輸入，也不自動處理該資料夾。

目前對應功能：

```bash
openshelf acsm-open --dry-run
openshelf acsm-open
openshelf acsm-report
```

## Calibre 的角色

Calibre 是電子書管理工具，包含桌面介面與 CLI，例如 `calibredb`。

OpenShelf 對無 DRM EPUB/PDF 提供兩種交接目標：

- 匯入 Calibre 書庫。
- 開啟給 ADE 或系統預設程式閱讀。

OpenShelf 不做下列事情：

- 不匯入 `.acsm` 到 Calibre。
- 不掃描 ADE 的 `My Digital Editions` 目錄做轉換或批次處理。
- 不安裝、不設定、不呼叫任何 DRM 移除外掛。
- 不把 Calibre 當成解除保護工具。

目前對應功能：

```bash
openshelf ebook-open --target ade --dry-run
openshelf ebook-open --target ade
openshelf ebook-report --target ade
openshelf calibre-import --dry-run
openshelf calibre-import
openshelf calibre-report
```

桌面版的 EPUB/PDF 分頁提供目標下拉選單，可選 Calibre 或 ADE。

## 關於其他下載或轉換工具

外部資料常會提到一些第三方工具，例如：

- Google Books Downloader 類工具。
- Epubor Ultimate 類商業電子書工具。
- Calibre 外掛生態系。

這些工具可能支援下載、匯入、轉檔，或宣稱能移除電子書 DRM。OpenShelf 不整合、
不推薦、也不提供這類解除保護流程。若某工具的主要用途或操作步驟包含移除 DRM、
抽取金鑰、在 ADE 之外 fulfill `.acsm`、解密或脫殼，該流程不屬於本專案範圍。

## 釐清常見誤解

### 「把 .acsm 拖進 ADE 就會解鎖嗎？」

不精確。ADE 會依 `.acsm` 領取並授權書籍，但書籍仍可能受 DRM 保護。
這是官方閱讀授權流程，不等於解除保護。

### 「Calibre CLI 可以批次處理電子書，所以 OpenShelf 能全部自動轉檔嗎？」

只能處理 OpenShelf 已判定為 `drm_free` 的 EPUB/PDF。若來源檔案仍受 DRM 保護，
OpenShelf 不會透過 Calibre 或外掛去移除保護。

### 「為什麼 repo 有 Calibre 交接功能，卻不處理 ADE 資料夾？」

因為 ADE 資料夾可能包含受 DRM 保護的授權檔案。OpenShelf 的 Calibre 交接功能只讀
manifest 中明確分類為 `drm_free` 且由 OpenShelf 直接下載成功的檔案。

## 專案設計結論

OpenShelf 的擴張方向是：

- 更穩定地枚舉 Google Play 圖書庫。
- 更可靠地下載官方可匯出檔。
- 更清楚地記錄 `.acsm`、無 DRM 檔案、失敗與無法匯出的書。
- 將無 DRM EPUB/PDF 交接到 Calibre 或 ADE。
- 產生人可讀報表，方便使用者後續處理。

OpenShelf 不會擴張成 DRM 移除、解密、外掛設定或 ACSM fulfill 工具。
