# 貢獻指南（Contributing）

感謝你對 OpenShelf 有興趣！這是一個小型工具，歡迎 issue 與 PR。送出前請花一分鐘讀完本頁，尤其是「**專案邊界**」一節 —— 跨越邊界的貢獻一律無法接受。

## 🧱 專案邊界（最重要，務必先讀）

OpenShelf 只做三件事：無 DRM 書下載 EPUB/PDF、DRM 書下載官方 `.acsm` 原樣存檔供 Adobe Digital Editions（ADE）閱讀、無法匯出的只記錄。

**以下方向的貢獻一律不接受，PR 會直接關閉：**

- 任何 DRM 規避、解密、脫殼。
- 解析 `.acsm` 內容、在 ADE 之外自行 fulfill、抽取 Adobe ADEPT／金鑰。
- 移除或破壞任何電子書的保護措施。
- 整合、推薦或內建上述用途的第三方工具或相依套件。

`.acsm` 只做兩件事：**下載**、**原樣存檔**。背景說明見 [`docs/third-party-ebook-tooling.md`](docs/third-party-ebook-tooling.md)。

## 🛠️ 開發環境

需要 Python 3.11+。

```bash
git clone https://github.com/SanHsien/openshelf.git
cd openshelf
pip install -e ".[gui]"     # 含桌面 UI 相依；只測 CLI 可省略 [gui]
```

## ✅ 送出前的檢查

1. **跑測試**（純函式、不需網路、不需瀏覽器、不需登入態）：

   ```bash
   python -m unittest discover -s tests
   ```

   CI 會在 Python 3.11／3.12／3.13 上跑同一組測試，全綠才會通過。

2. **新功能請附測試**。本專案用標準庫 `unittest`，測試放在 `tests/`。

3. **改到端點邏輯**（`openshelf/playbooks.py`）時，請說明你觀察到的回應結構，不要把任何個人 cookie／token／登入態貼進程式碼、commit 或 PR。

4. **風格**：最小干預 —— 不主動大改命名、不引入新架構；沿用現有風格與繁體中文註解。

## 🔒 不要提交的東西

`storage_state.json`、`.profile/`、`output/`（含已下載的書、`.acsm`、報表）已列入 `.gitignore`，請勿移除或繞過。**絕不要**把帳號 cookie、Authorization 標頭、任何個資或書檔放進版控。

## 📥 提交流程

1. Fork 並開一個分支。
2. 提交（commit message 用清楚的描述即可）。
3. 確認測試全綠。
4. 開 PR，說明動機與改了什麼；若涉及端點，附上你的觀察。

## 📝 授權

送出貢獻即表示你同意你的貢獻以本專案的授權 **[Apache License 2.0](LICENSE)** 釋出。
