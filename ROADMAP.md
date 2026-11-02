# 路線圖

> 本 repo 後續工作的單一真相源。做完一項，就在同一個 commit 刪掉那一列；新工作只加在這裡。
> 現況段的數字是 2026-10-29 依 `main` `45fa953e808a` 查的快照，開工前先重查 GitHub。

## 現況

公開版核心：只下載無 DRM 的 EPUB/PDF，DRM 書只原樣存檔官方 `.acsm`（邊界見 `AGENTS.md`「專案宗旨與邊界」）。2026-11-02 快照：open PR 1（Dependabot #34 待維護者依 deferral 關閉）；Dependabot 與 code scanning 告警皆 0；CI、CodeQL、依賴新鮮度、Dependabot guarded merge 在 `main` 最近一次皆 success；最近 release v1.0.4（2026-08-08）。open issue #1「依賴新鮮度檢查：需要維護」，直接依賴中 `playwright` 已 DEFERRED；`ruff` 0.17.3 已加 deferral，待 `main` 上的 workflow 刷新與 #34 關閉後，issue #1 由 tracker 自動關閉。

**與 `openshelf-personal` 的分工**：本 repo 擁有「共用核心」的所有後續工作（掃描、匯出、manifest、設定、doctor、release 流程設計與測試補強）。私人 GPL 版的路線圖只認領 DeDRM／fulfill 相關項目，以及「待本 repo 先做完後移植」的對應列；本 repo 不認領任何解密、ACSM 解析或金鑰相關工作。

## 近期：可以直接動手
| 項目 | 為什麼 | 驗收方式 | 建議執行者 | 證據 |
| --- | --- | --- | --- | --- |
| 關閉 Dependabot #34 並確認 issue #1 自動關閉 | ruff 0.17.3 已依 `.github/dependency-deferrals.json` 延後；tracker 只在無 open Dependabot PR 時自動關 | deferral 已在 `main` 上之後，在 #34 留言引用 deferral 再關閉；之後 `gh issue view 1 --repo SanHsien/openshelf --json state` 為 CLOSED（不手動關 issue） | 維護者 | issue #1；PR #34；`.github/workflows/dependency-freshness.yml:175-199` |

## 中期：等條件成立再做
| 項目 | 觸發條件 | 驗收方式 | 建議執行者 | 證據 |
| --- | --- | --- | --- | --- |
| 評估是否區分單本 403 與登入過期 | 維護者取得真實書庫中單本 403 的樣本 | 決定是否區分單本無權限與登入過期；要區分時先寫失敗測試 | 維護者 | `REPO_REVIEW.md:101`；`openshelf/playbooks.py:150` |
| 實機驗證 total／可解析數一致，再決定是否放寬「取不齊就 fail closed」 | 維護者在登入狀態下自行跑 `openshelf scan`（2026-10-28 一次實機結果為 exit 0、無 IncompleteLibrary，報表在維護者本機）；若日後 scan 回報 IncompleteLibrary 才需處理 | 以 `openshelf doctor` 與 `scan` 輸出比對 Google 宣告總數與可解析數，記錄在 `REPO_REVIEW.md`；不一致時另開失敗測試再修 | 維護者 | `REPO_REVIEW.md` 已下架段落；接續開發報告（2026-10-25） |
| Release constraints／lock、SBOM、打包產物離線啟動 smoke | 上列 release preflight 已落地且穩定一個發版週期 | release workflow 產出依賴清單附件；smoke step 在三平台 import 並建立 GUI 後關閉、不連網；以一次 dry run 全綠為證 | Claude Opus | `REPO_REVIEW.md:169,172,173,228` |
| 補 GUI 取消流程測試 | 有人決定引入可無頭執行 PySide6 的測試手段（如 offscreen platform）且 CI 能穩定跑 | 取消後 manifest 完整、無 `.part` 殘留的測試綠；`REPO_REVIEW.md:100` 回註 | Claude Sonnet | `REPO_REVIEW.md:100` |
| GUI 表格顯示「已下架」標記 | 維護者決定要加（CLI、報表、CSV、HTML 已有） | GUI 表格出現狀態欄，截圖或離線 GUI smoke 驗證 | 維護者 | 深掃報告（2026-10-26）「刻意不修」段 |

## 刻意不做
| 不做什麼 | 理由 | 什麼情況下重新考慮 |
| --- | --- | --- |
| 任何 DRM 規避、解密、ACSM 解析、金鑰抽取 | 公開版硬性邊界，`.acsm` 只下載與原樣存檔（`AGENTS.md`「硬性邊界」）；這類工作屬私人 GPL 版 `openshelf-personal` | 不重新考慮；需求往這個方向時停下來告知維護者 |
| 把 macOS／Linux 使用者資料移出 app bundle | 維護者 2026-10-25 決定維持現狀（`REPO_REVIEW.md:226` 已劃掉） | 維護者改變決定，或有實機回報資料目錄不可寫 |
| 為了啟用 branch protection／secret scanning 而改變「直推 main」慣例 | 個人開發慣例，見 `AGENTS.md`「開發原則」 | 出現第二位協作者 |
| 手動關閉依賴新鮮度 tracker issue | workflow 自己開關，手動關會被重開並掩蓋根因 | 不重新考慮 |

## 維護方式

自有 repo，非 fork。依賴由 Dependabot 每週與新鮮度 workflow 每月處理，runtime／GUI／build 與所有 major 人工審查（`AGENTS.md`「依賴維護」）；合併任何 PR 前先 `gh pr diff`。改動共用核心後，在 `openshelf-personal` 的路線圖對應列觸發移植。
