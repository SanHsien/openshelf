<!-- 感謝貢獻！送出前請確認以下項目。 -->

## 這個 PR 做了什麼
<!-- 簡述動機與改動 -->

## 變更類型
- [ ] Bug 修正
- [ ] 新功能
- [ ] 文件
- [ ] 重構／維護

## 🧱 專案邊界自我檢查（必填）
- [ ] 我的改動**不涉及** DRM 規避／解密／脫殼。
- [ ] 我的改動**不解析 `.acsm` 內容**、不在 ADE 之外 fulfill、不抽取金鑰。
- [ ] 我**沒有**移除或破壞任何電子書的保護措施，也沒有引入這類用途的相依套件。

> 跨越上述邊界的 PR 無法被接受。背景見 [`docs/third-party-ebook-tooling.md`](../docs/third-party-ebook-tooling.md)。

## 測試
- [ ] `python -m unittest discover -s tests` 全數通過。
- [ ] 新增／修改的行為有對應測試（如適用）。

## 其他
- [ ] 沒有把任何登入態、cookie、Authorization 標頭、個資或書檔放進版控。
