# README 截圖產生流程

README 主畫面截圖固定由腳本產生：

```bash
python tools/generate_readme_screenshot.py
```

輸出檔案：

```text
docs/screenshots/main-window.png
```

這個腳本會：

- 建立暫存 `config` / `output` / `manifest.json`。
- 寫入固定的假書庫資料。
- 啟動 PySide6 主視窗，停用更新檢查與首次啟動導覽。
- 使用 `QWidget.grab()` 直接擷取 OpenShelf 視窗，不擷取桌面畫面。

注意事項：

- 不要用真實 `output/manifest.json` 或本機書庫資料產生公開截圖。
- 不要用全桌面截圖，避免截入私人視窗或通知。
- 修改主視窗 UI 後，請重跑此腳本並檢查圖片。
