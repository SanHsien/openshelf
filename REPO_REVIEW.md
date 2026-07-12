# OpenShelf 專案覆核

覆核日期：2026-07-12

基準：`origin/main` / `58c61dd`

範圍：Python 程式碼、測試、文件、套件建置、GitHub Actions、Release 與 repo 安全設定。

## 結論

OpenShelf 的產品邊界清楚，程式碼也有確實遵守：ACSM 僅下載、原樣存檔與交給系統預設程式，不解析、不轉換、不在 ADE 之外 fulfill。下載採暫存檔、覆核後取代，manifest 採原子寫入，整體架構適合目前的小型桌面工具。

目前沒有發現 P0 阻斷問題，但在下一版 Release 前應先處理五項 P1：

1. 防止不同書目在檔名正規化後碰撞並互相覆寫。
2. 未知下載格式必須 fail closed，不能預設為無 DRM EPUB。
3. 書庫分頁未取齊時必須明確失敗，不能提交不完整 manifest。
4. 修正目前 `main` 與既有 Release tag 歷史斷開的發布風險。
5. 為真正協調使用者資料的 `scan` / `export` 主流程補整合測試。

## 實測證據

| 檢查 | 結果 |
|---|---|
| 遠端基準 | `main`、`origin/main` 均為 `58c61dd`；覆核開始前工作樹乾淨 |
| GitHub CI | `58c61dd` 的最新 CI 成功，Python 3.11 / 3.12 / 3.13 |
| 單元／整合測試 | `python -m unittest discover -s tests -v`：105 項全數通過 |
| 語法 | `python -m compileall -q app.py build_exe.py openshelf tests tools`：通過 |
| 隔離安裝 | 全新 venv 中 editable install、`pip check`、105 項測試均通過 |
| 套件建置 | 成功產出 `openshelf-1.0.3-py3-none-any.whl` |
| Ruff | production code 1 項錯誤；tests 2 項錯誤；目前 CI 未執行 lint |
| Coverage | 全套測試 line coverage 41%；`scan`、`export`、CLI、GUI、瀏覽器登入流程未被執行 |
| 相依安全 | GitHub Dependabot open alerts：0 |
| 機密掃描 | tracked files 未找到 cookie、Authorization token、私鑰等憑證；`playbooks.py` 的 Google 網頁公開 API key 屬已知設計，不視為私密金鑰 |
| Release | 最新 Release 為 `v1.0.3`，跨平台資產與 SHA256 檔案齊全 |

本輪沒有用真實 Google 帳號執行 `login` / `scan` / `export`，也沒有在 macOS、Linux 或打包後 GUI 做實機操作。因此端點現況、Google 帳號風控、ADE 交接成功率與非 Windows 執行體驗不在本輪已驗證範圍內。

## 發現與建議

### P1：檔名正規化碰撞會讓兩本書指向同一檔案

證據：`openshelf/service.py:395-398` 先用原始書名、作者分組；`openshelf/export.py:37-50` 到產生檔名時才替換 Windows 非法字元與截斷。實測 `A/B - 作者` 與 `A:B - 作者` 都產生 `A_B - 作者.epub`，`openshelf/export.py:105` 會讓後一次下載直接取代同名目的檔。

影響：後下載的書會覆寫先下載的書，兩筆 manifest 可能同時指向同一檔案。這是使用者資料錯置，不只是檔名不好看。

建議：以「最終正規化後的完整檔名」做全域碰撞檢查；只要碰撞就固定加入 `volume_id`。測試至少涵蓋非法字元碰撞、180 字截斷碰撞，以及同書名但 metadata 不完整的情況。

### P1：未知格式代碼被預設成 EPUB，應改為 fail closed

證據：`openshelf/playbooks.py:263-268` 對未知兩欄格式使用 `_FMT_CODE.get(entry[0], "epub")`。實測格式碼 `999` 會產生 `ExportOption(fmt="epub", ...)`，上層進而分類為 `drm_free`。

影響：Google RPC schema 改版或新增格式時，OpenShelf 可能把未知格式誤判成可直接匯出的無 DRM EPUB。ZIP magic 只能證明容器像 EPUB，不能證明未知格式的授權語意。這也不符合本專案對 DRM 邊界應採的保守策略。

建議：未知格式碼直接略過並記錄 schema 不相容；若當頁存在未知下載格式，`doctor` / `scan` 應提示更新 `playbooks.py`，不可猜成 EPUB。補一個 unknown-code 回歸測試。

### P1：分頁未取齊時會靜默接受部分書庫

證據：`openshelf/playbooks.py:198-206` 即使已知 `total` 大於實際取得數，只要沒有 next token、token 重複或到達 `_MAX_PAGES` 就直接回傳部分清單。`tests/test_integration.py:92-100` 目前把「total=99、只取得 1 筆且沒有 token」視為正常停止。

影響：使用者會得到不完整 manifest、下載與報表，畫面卻沒有告知漏書。若後續實作 stale-item 同步，這種部分掃描還可能把大量正常書誤標為 inactive。

建議：只要回應提供 `total` 且 `len(books) < total`，卻無法繼續分頁，就拋出明確的 incomplete-scan 錯誤；達 `_MAX_PAGES` 也同樣失敗。部分結果可供診斷，但不得當成完整 scan 寫回權威 manifest。

### P1：Release tag 與目前 `main` 沒有共同祖先

證據：

- `git merge-base v1.0.3 main` 回傳失敗。
- GitHub compare API 回覆 `No common ancestor between v1.0.3 and main`。
- `.github/workflows/release.yml:88-92` 使用 `gh release create --generate-notes`。

影響：下一個 tag 雖可從目前 `main` 建置，但 GitHub 無法正常比較 `v1.0.3...新版本`。自動產生 release notes 可能失敗或失去可信的版本差異，使用者也無法從 tag 追溯連續演進。

建議：

- 保留已公開的 `v1.0.3`，不要重寫或刪除既有 Release。
- 下一版做一次性的「歷史重建後首發」：使用人工整理的 release notes，不依賴 `--generate-notes`。
- 後續所有 tag 都從目前 `main` 的後代建立，恢復連續歷史。
- Release workflow 增加 preflight：確認上一個可比較 tag 是 `HEAD` 的祖先；不成立時停用自動 notes 並給出明確錯誤。

### P1：真正的 `scan` / `export` 協調流程沒有整合測試

證據：coverage 顯示 `openshelf/service.py:330-492` 未執行；現有測試主要覆蓋 parser、分類、報表、ACSM 時效、檔名與小型 helper。105 項測試全綠，但沒有直接驗證「登入態 client → 列舉 → manifest → 下載 → 失敗續傳」這條主路徑。

影響：最容易造成使用者書庫狀態錯誤、舊檔被誤判、下載失敗後 manifest 不一致的地方，現在只能靠程式碼閱讀與人工操作發現。

建議優先補下列 mock-httpx / fake-client 測試：

- [ ] `scan` 新增書、更新 metadata、保留既有已下載檔案。
- [ ] `export` EPUB 失敗後改試 PDF，成功後正確更新 manifest。
- [ ] 下載或覆核失敗時不覆蓋舊檔，且保留可診斷的 `note`。
- [ ] `refresh_acsm` / `force_refresh_acsm` / `limit` / 已送出 ACSM 的組合行為。
- [ ] GUI 取消時停止在安全邊界，不留下半寫 manifest 或 `.part` 檔。
- [ ] 401 / 403 中止整批並顯示重新登入提示。

### P2：`scan` 只合併，不處理已不在當次書庫中的舊項目

證據：`openshelf/service.py:333-355` 載入既有 manifest，逐筆 upsert 當次回應，但沒有標記或移除本次未見的 volume id。

影響：若書籍被退款、移除、區域權限改變，或端點只回傳不完整資料，報表總數可能永久保留舊項目。直接刪除也不安全，因為短暫端點異常可能造成誤刪紀錄。

建議：明確定義同步政策。較安全的做法是增加 `last_seen_at` / `in_library`，完整 scan 成功後把未見項目標成 inactive，報表預設分開列示；不要自動刪除已下載檔案。

### P2：CI 沒有 lint gate，現況已有可偵測錯誤

證據：

- `openshelf/ui/i18n.py:64` 與 `openshelf/ui/i18n.py:91` 重複定義字典鍵 `作者`；後者會靜默覆蓋前者。
- `tests/test_service.py:181`、`tests/test_service.py:183` 在一行放兩個敘述。
- `.github/workflows/ci.yml:30-36` 只安裝套件並跑 unittest。

影響：目前重複鍵剛好是相同值，沒有造成畫面錯誤，但同類問題若值不同，Python 不會在執行時告警，CI 也會繼續全綠。

建議：

- [ ] 移除重複字典鍵並拆開測試中的分號敘述。
- [ ] 在開發相依與 CI 加入 `ruff check .`。
- [ ] 可再加 `python -m compileall` 與 wheel build，確保發佈面持續可安裝。

### P2：登入態含敏感 cookie，但存檔後沒有權限強化

證據：`openshelf/browser.py:90` 直接寫出 `storage_state.json`；`.gitignore` 已正確排除，但程式沒有在存檔後限制檔案權限，也沒有在 `doctor` 中檢查權限。

影響：這不是遠端漏洞，但在共用電腦、寬鬆 umask、備份同步或其他本機帳號可讀的環境中，登入態可能被非預期存取。

建議：

- Unix 系統寫出後 best-effort 設為 `0600`。
- Windows 明確提示檔案位置與敏感性；若要進一步強化，可限制為目前使用者 ACL。
- `doctor` 增加登入態位置、是否被版控追蹤、Unix 權限是否過寬的檢查，但不要輸出 cookie 值。

### P2：macOS / Linux 打包版把可寫資料放在 executable 旁

證據：`openshelf/config.py:52-55` 在 frozen 模式以 executable 所在目錄為根。macOS 的 executable 位於 `OpenShelf.app/Contents/MacOS/`，因此預設 `.profile`、`storage_state.json` 與 `output/` 會落進 app bundle；Linux 若放在系統程式目錄也有同類問題。

影響：安裝位置可能不可寫；即使可寫，把登入態與下載資料塞進 app bundle 也會破壞應用程式內容完整性，升級或移除程式時還可能一併遺失使用者資料。README 已標明 macOS / Linux 尚未實機測試，因此這應視為發布前待驗證的跨平台風險。

建議：設定與登入態改放 OS 使用者資料目錄；下載輸出放 Documents / Downloads 下的 OpenShelf 目錄或首次啟動時讓使用者選擇。Windows 可保留 portable 模式，但應與正式安裝模式明確分開，並提供舊路徑遷移。

### P2：CSV 報表可被書目 metadata 觸發公式解析

證據：`openshelf/service.py:231-250` 將書名、作者、出版社與備註原樣寫入 CSV，README 又明確讓使用者用 Excel 開啟。實測 `=HYPERLINK(...)` 會原樣成為 CSV 第一欄。

影響：以 `=`、`+`、`-`、`@` 開頭的遠端 metadata 可能被試算表視為公式。來源通常是出版社 metadata，風險不高，但輸出層可以低成本消除。

建議：只在 CSV 輸出層對危險開頭加前置單引號，manifest 仍保留原值；補公式注入測試。HTML 路徑已使用 `html.escape`，本項不影響 HTML 報表。

### P2：Release 建置不可重現，且缺少產物 smoke test

證據：`pyproject.toml` 僅設相依套件下限；`.github/workflows/release.yml:32-38` 與 `116-122` 每次安裝當下最新版再打包。Release workflow 沒有先跑測試、沒有驗證 tag 與 `pyproject.toml` / `openshelf.__version__` 一致，建完 zip / installer 後也沒有啟動或 import 產物。

影響：相同 tag 在不同時間重跑可能得到不同依賴組合；上游套件回歸也可能在 Release 當天才出現。Build 成功只代表 PyInstaller 完成，不代表程式能啟動。

建議：

- [ ] 為 Release 使用經 CI 驗證的 constraints / lock，定期由 Dependabot 或排程更新。
- [ ] Release job 先跑完整測試，並驗證 tag、package metadata、UI 版本三者一致。
- [ ] 確認發布 tag 指向允許的 `main` commit，避免任意 `v*` tag 直接發布未審查二進位。
- [ ] 保存建置時的相依版本清單或 SBOM。
- [ ] 打包後至少做離線啟動 smoke：import 主要模組、載入設定、建立 GUI 後立即關閉；不接觸真實登入態或 Google 端點。

### P3：文件與實際測試數不同

證據：README `README.md:272` 寫「共 99 個單元／整合測試」，實測為 105。

建議：若保留數字，改成 105；更耐維護的做法是移除固定數字，改寫成「測試涵蓋……，以 CI 結果為準」。

### P3：公開 repo 的治理 gate 尚未啟用

現況：`main` 未設定 branch protection；GitHub secret scanning / push protection 與 code scanning 未啟用。Dependabot security updates 已啟用且目前沒有 open alert。

建議：若 repo 會接受外部 PR，至少要求 CI 必須成功後才能合併，並啟用 secret scanning / push protection。CodeQL 對此小型 Python 專案不是發布阻斷項，但可作為低成本的定期安全檢查。

### P3：版本資訊有兩個手動來源

現況：`pyproject.toml:3` 與 `openshelf/__init__.py:7` 都寫 `1.0.3`，目前一致。

建議：發版前加一致性測試，或讓其中一處由 package metadata 讀取，避免 UI、wheel 與 tag 版本日後分叉。

## 建議執行順序

### 下一版 Release 前

- [ ] 修正檔名正規化碰撞，補資料不覆寫測試。
- [ ] 未知下載格式改成 fail closed。
- [ ] 分頁未取齊時明確失敗，不提交部分 manifest。
- [ ] 決定並實作「斷開歷史後首次發版」策略，避免依賴自動 compare notes。
- [ ] 補 `scan` / `export` 主流程整合測試。
- [ ] 清掉 Ruff 問題，將 lint 加入 CI。
- [ ] 更新 README 的測試敘述。

### 下一個維護週期

- [ ] 定義 manifest 對已移除書籍的同步政策。
- [ ] 強化 `storage_state.json` 權限與 `doctor` 提示。
- [ ] 把 macOS / Linux 使用者資料移出 executable / app bundle，做目標平台實機驗證。
- [ ] 防護 CSV 公式注入。
- [ ] 導入 Release constraints / SBOM 與打包產物 smoke test。
- [ ] 視協作需求啟用 branch protection、secret scanning 與 CodeQL。

## 已確認不是問題

- `openshelf/playbooks.py` 中的 Google API key 是網頁版公開 key，真正授權仍依使用者本機 SAPISID cookie；不應把它誤報成已洩漏的私密 API key。
- `ACSM_MAX_BYTES` 僅以大小做誤判保護，程式沒有讀取或解析 ACSM XML，符合專案硬性邊界。
- Calibre 與一般閱讀器交接只處理 manifest 中的 `drm_free` EPUB/PDF；`.acsm` 不會匯入 Calibre。
- 本機全域 `pip check` 的缺件屬其他已安裝工具；隔離 venv 的 OpenShelf 相依檢查為乾淨，不能把全域環境雜訊列為本專案缺陷。
