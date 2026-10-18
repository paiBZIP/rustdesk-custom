# RustDesk 客製化伺服器設定與跨平台打包維護手冊 (FIX_RUSTDESK)

本手冊詳細記錄本次 RustDesk 客製化「專屬伺服器設定」、「金鑰更新」、「新版本升級步驟」與「GitHub Actions 跨平台自動打包 (Windows / Ubuntu / Mac MINI)」的完整流程與關鍵踩坑修復。

---

## 目錄
1. [專案參數配置現況](#1-專案參數配置現況)
2. [如何修改金鑰 (KEY) 與伺服器網址](#2-如何修改金鑰-key-與伺服器網址)
3. [如何升級新版本號 (Version Bump)](#3-如何升級新版本號-version-bump)
4. [三平台自動打包操作說明 (CI/CD)](#4-三平台自動打包操作說明-cicd)
5. [實戰踩坑紀錄與重要修復清單 (Troubleshooting & Fixes)](#5-實戰踩坑紀錄與重要修復清單-troubleshooting--fixes)

---

## 1. 專案參數配置現況

目前版本已內建並鎖定以下自訂連線參數：

| 項目 | 內嵌設定值 | 說明 |
| :--- | :--- | :--- |
| **金鑰 (Public Key)** | `k09QlRj3SkGwORP6Kg39KkOpRdbXGfoz3LN9QzfzXpk=` | 官方預設已替換為您的專屬金鑰 |
| **ID 伺服器** | `vpn.xbmax.com` | 預設監聽 Port 21116 |
| **中繼伺服器 (Relay)** | `vpn.xbmax.com` | 預設監聽 Port 21117 |
| **介面視覺隱藏** | **完全空白隱藏** | 在連線設定中不填寫時維持空白，底層自動回退至上述內嵌伺服器 |

---

## 2. 如何修改金鑰 (KEY) 與伺服器網址

未來若需更換金鑰（Key）或更換伺服器網域名稱（Domain/IP），請修改以下檔案：

### ① 修改核心預設常數
- **檔案路徑**：[`libs/hbb_common/src/config.rs`](file:///c:/Users/Bzip/Desktop/rustdesk-master/libs/hbb_common/src/config.rs)
- **修改內容**：
  ```rust
  // 1. 修改 ID 伺服器 (Rendezvous Server)
  pub const RENDEZVOUS_SERVERS: &[&str] = &["vpn.xbmax.com"];

  // 2. 修改 公鑰 (Public Key)
  pub const RS_PUB_KEY: &str = "k09QlRj3SkGwORP6Kg39KkOpRdbXGfoz3LN9QzfzXpk=";

  // 3. 修改 中繼伺服器常數 (Default Relay Server)
  pub const DEFAULT_RELAY_SERVER: &str = "vpn.xbmax.com";
  ```

### ② 確保預設中繼伺服器自動回退 (Fallback)
- **檔案路徑**：[`src/rendezvous_mediator.rs`](file:///c:/Users/Bzip/Desktop/rustdesk-master/src/rendezvous_mediator.rs)
  ```rust
  if host.is_empty() {
      host = config::DEFAULT_RELAY_SERVER.to_owned();
  }
  ```
- **檔案路徑**：[`src/client.rs`](file:///c:/Users/Bzip/Desktop/rustdesk-master/src/client.rs)
  ```rust
  let relay_server = if relay_server.is_empty() {
      let opt = Config::get_option("relay-server");
      if !opt.is_empty() {
          opt
      } else {
          config::DEFAULT_RELAY_SERVER.to_owned()
      }
  } else {
      relay_server.to_string()
  };
  ```
- **檔案路徑**：[`libs/hbb_common/src/websocket.rs`](file:///c:/Users/Bzip/Desktop/rustdesk-master/libs/hbb_common/src/websocket.rs)
  ```rust
  let mut relay_server = Config::get_option(keys::OPTION_RELAY_SERVER);
  if relay_server.is_empty() {
      relay_server = DEFAULT_RELAY_SERVER.to_owned();
  }
  ```

---

## 3. 如何升級新版本號 (Version Bump)

當發布新版本（例如從 `1.5.1` 升級到 `1.5.2`）時，請依照順序修改以下 4 個檔案：

1. **根目錄專案配置**：[`Cargo.toml`](file:///c:/Users/Bzip/Desktop/rustdesk-master/Cargo.toml)
   ```toml
   [package]
   name = "rustdesk"
   version = "1.5.2"
   ```
2. **Flutter 專案配置**：[`flutter/pubspec.yaml`](file:///c:/Users/Bzip/Desktop/rustdesk-master/flutter/pubspec.yaml)
   ```yaml
   version: 1.5.2+1
   ```
3. **Windows 可攜版封裝器配置**：[`libs/portable/Cargo.toml`](file:///c:/Users/Bzip/Desktop/rustdesk-master/libs/portable/Cargo.toml)
   ```toml
   [package]
   name = "rustdesk-portable-packer"
   version = "1.5.2"
   ```
4. **GitHub Actions 打包腳本環境變數**：[`.github/workflows/package-custom.yml`](file:///c:/Users/Bzip/Desktop/rustdesk-master/.github/workflows/package-custom.yml)
   ```yaml
   env:
     VERSION: "1.5.2"
   ```

修改完成後，使用 Git 提交並推送到 GitHub：
```bash
git add .
git commit -m "bump: upgrade version to 1.5.2"
git push origin main
```
推送後 GitHub Actions 會**自動觸發全新三平台的打包流程**！

---

## 4. 三平台自動打包操作說明 (CI/CD)

工作流程定義於 [`.github/workflows/package-custom.yml`](file:///c:/Users/Bzip/Desktop/rustdesk-master/.github/workflows/package-custom.yml)。

### 觸發方式
1. **自動觸發**：只要推送到 GitHub `main` 或 `master` 分支，CI 即自動執行。
2. **手動觸發**：在 GitHub 儲存庫頁面點擊 **Actions** ➔ 選擇 **Custom Package (Windows, Ubuntu, Mac MINI)** ➔ 點擊 **Run workflow**。

### 產出檔案規格
編譯完成後，產物可直接在 Actions 頁面下載，或同步放置於本機 `OUT/`：
- 🖥️ **Windows**：`rustdesk-{VERSION}-x86_64.exe`（可攜版兼安裝版）
- 🐧 **Ubuntu**：`rustdesk-{VERSION}.deb`（標準 Debian / Ubuntu x86_64 套件）
- 🍎 **Mac MINI**：`rustdesk-{VERSION}-aarch64.dmg`（Apple Silicon M 系列 原生映像檔）

---

## 5. 實戰踩坑紀錄與重要修復清單 (Troubleshooting & Fixes)

本次建置過程中排查並修復了以下關鍵問題，後續維護請特別留意：

### ① `hbb_common` 模組追蹤（關鍵！）
- **問題**：`libs/hbb_common` 原始為 Git Submodule，如果直接以子模組方式運作，GitHub Actions 在執行時會從官方倉庫拉取純淨程式碼，導致所有自訂的 Key 與伺服器被官方設定覆蓋。
- **解法**：移除了 `.gitmodules` 與 `libs/hbb_common/.git`，直接將 `libs/hbb_common` 作為主專案的原生存檔納入 Git 追蹤。

### ② 圖示與 UI 資源被 `.gitignore` 誤刪
- **問題**：原始 `.gitignore` 中存在 `*png`, `*svg`, `*jpg` 規則，導致工作列圖示（如 `res/mac-tray-dark-x2.png`、`128x128@2x.png`、Flutter 所有 SVG 向量圖）在初次 `git add` 時全數遺失，導致編譯期報錯 `No such file or directory`。
- **解法**：修改 `.gitignore`，刪除對圖檔的忽略，並將全部 122 個官方圖示與 UI 資源檔案強制補齊納入版本控制。

### ③ Rust 型別匹配問題
- **問題**：`src/client.rs` 中 `let relay_server = if ...` 在自訂 fallback 時，`if` 分支回傳 `String`，而 `else` 分支直接回傳了 `&str`，導致編譯錯誤 `error[E0308]: if and else have incompatible types`。
- **解法**：在 `else` 分支呼叫 `relay_server.to_string()` 統一回傳型別。

### ④ Ubuntu Linux 連結器相依性缺失
- **問題**：
  - 缺少 `libpulse-dev` 與 `libasound2-dev`，導致 `/usr/bin/ld: cannot find -l:libpulse-simple.so.0`。
  - 缺少 `libxcb-randr0-dev`, `libxcb-shape0-dev`, `libxcb-xfixes0-dev`, `libxfixes-dev`，導致 `/usr/bin/ld: cannot find -lxcb-randr`。
  - 缺少 `libunwind-dev` 導致 GStreamer 相依衝突。
- **解法**：在 `package-custom.yml` 中完整補足所有音訊與 XCB 開發標頭庫。

### ⑤ Debian 套件封裝權限（dpkg-deb 錯誤）
- **問題**：Linux 應用程式已編譯成功，但在執行 `dpkg-deb -b tmpdeb rustdesk.deb` 時報錯：
  `dpkg-deb: error: maintainer script 'preinst' has bad permissions 644 (must be >=0555 and <=0775)`。
  原因是 Windows 簽入 Git 時檔案權限預設為 644。
- **解法**：
  1. 在 `build.py` 封裝前自動調用 `system2('chmod 755 tmpdeb/DEBIAN/*')`。
  2. 在 `package-custom.yml` 打包前執行 `chmod -R 755 res/DEBIAN`。
  3. 透過 `git update-index --chmod=+x res/DEBIAN/*` 將維護腳本在 Git 中標記為可執行檔。

### ⑥ Windows VCPKG 靜態編譯與自訂 Flutter Engine
- **問題**：Windows 找不到 `libavutil/attributes.h`。原因是 `vcpkg.json` 中的 ffmpeg 帶有 `"host": true`，預設會使用動態 triplet 導致靜態庫目錄遺失。
- **解法**：
  1. 設定 `VCPKG_DEFAULT_HOST_TRIPLET: x64-windows-static`。
  2. 下載並替換 RustDesk 官方客製之 `windows-x64-release.zip` Flutter Engine，解決 Windows 下拖動視窗與多螢幕渲染問題。
  3. 安裝 `rustfmt` 工具鏈。

### ⑦ Mac MINI (macOS-14 Apple Silicon) 權限
- **問題**：GitHub Actions macOS 執行時 `./build.py: Permission denied`。
- **解法**：將 `build.py` 權限更新為 `100755`，並使用 `python3 ./build.py ...` 明確指定 Python 直譯器呼叫。

---

## 6. 視窗型圖形管理工具 (RustdeskTool.py)

為了方便日後快速查看、修改金鑰與伺服器，並實現一鍵推送與雲端打包，專案內附有專屬圖形介面工具：

### 啟動方式
- **方式一（最快）**：直接雙擊執行目錄下的 [`啟動工具.bat`](file:///c:/Users/Bzip/Desktop/rustdesk-master/啟動工具.bat) 或 [`RustdeskTool.bat`](file:///c:/Users/Bzip/Desktop/rustdesk-master/RustdeskTool.bat)。
- **方式二**：在終端機執行：
  ```bash
  python RustdeskTool.py
  ```

### 主要功能
1. **快速查看 / 修改**：
   - **Public Key（金鑰）**：支援一鍵複製、隨機產生 32-byte Ed25519 金鑰。
   - **ID 伺服器**：預設 `vpn.xbmax.com`，附有 **「⚡ 測試連線 (21116)」** 實時端口連通性檢測。
   - **中繼伺服器**：預設 `vpn.xbmax.com`，附有 **「⚡ 測試連線 (21117)」** 檢測。
   - **版本號**：儲存時自動同步更新 `Cargo.toml`、`pubspec.yaml`、`libs/portable/Cargo.toml` 與 CI 腳本。
2. **一鍵儲存並上傳 GitHub（自動觸發雲端打包）**：
   - 點擊 **「🚀 一鍵儲存並上傳 GitHub」** 按鈕，工具會自動儲存設定、建立 Git Commit、Push 至 GitHub 儲存庫。
   - GitHub Actions 偵測到 Push 後立即啟動雲端編譯流程。
3. **即時監控雲端編譯狀態**：
   - 工具會透過 GitHub API 實時顯示各 Job（Windows / Ubuntu / Mac MINI）的即時進度。
4. **一鍵下載最新安裝包至 OUT**：
   - 編譯完成後，點擊 **「📥 下載最新安裝包至 OUT」**，工具會自動下載 `OUT` 產物並解壓縮至本地 `OUT/` 資料夾，隨後自動開啟檔案總管。

---

*文檔建立時間：2026-10-18*
*紀錄標記：FIX_RUSTDESK*
