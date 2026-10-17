# RustDesk 三平台打包說明 (Windows / Ubuntu / Mac MINI)

此目錄 `/OUT/` 用於存放打包完成的安裝檔案：
- **Windows 版本**：`rustdesk-1.5.1-x86_64.exe`（包含安裝版與便攜版）
- **Ubuntu 版本**：`rustdesk-1.5.1-x86_64.deb`（Debian / Ubuntu 安裝包）
- **Mac MINI 版本**：`rustdesk-1.5.1-aarch64.dmg`（Apple Silicon M 系列晶片專用）

---

## 為什麼需要官方打包方式（GitHub Actions）？

1. **Mac MINI (.dmg) 跨平台限制**：
   - Apple 的 Xcode 工具鏈、macOS SDK 以及 `.dmg` 打包工具（`create-dmg`）受到 Apple 系統限制，**無法直接在 Windows 或 Linux 主機上進行跨平台編譯**。
   - RustDesk 官方團隊也是使用 **GitHub Actions 的 macOS (Apple Silicon) 雲端虛擬機** 進行編譯與輸出的。
2. **Ubuntu (.deb) 依賴庫**：
   - 需要 Linux 原生的 GTK3、GStreamer、libxdo、PAM 等系統函式庫。
3. **免去本機配置三種作業系統**：
   - 使用 GitHub Actions 可以同時啟動 Windows、Ubuntu、macOS 三台專用虛擬機並行打包，自動產出檔案。

---

## 方法一：使用專用 GitHub Actions 一鍵打包（最推薦，跟官方一致）

我們已經為您建立了一份專屬的工作流程檔案：
[`.github/workflows/package-custom.yml`](file:///c:/Users/Bzip/Desktop/rustdesk-master/.github/workflows/package-custom.yml)

### 操作步驟：
1. **上傳程式碼到您的 GitHub 儲存庫**：
   ```bash
   git init
   git add .
   git commit -m "Configure custom rendezvous server and keys"
   git remote add origin https://github.com/<您的帳號>/<您的儲存庫>.git
   git push -u origin master
   ```
2. **在 GitHub 網頁觸發打包**：
   - 進入您的 GitHub 儲存庫頁面。
   - 點選上方頁籤 **Actions**。
   - 在左側清單選擇 **Custom Package (Windows, Ubuntu, Mac MINI)**。
   - 點選右側按鈕 **Run workflow** -> 點擊綠色按鈕開始打包。
3. **下載成品到此目錄**：
   - 約等待 15~20 分鐘，三個平台編譯完成後，工作流程下方會出現名為 **OUT** 的 Artifact。
   - 點擊下載解壓縮後，將裡面的檔案直接放入此 `c:\Users\Bzip\Desktop\rustdesk-master\OUT\` 目錄即可！

---

## 方法二：若您有各別實體機器的本機打包指令

### 1. Windows 本機編譯：
- 必備環境：Visual Studio 2022 (C++ 工具)、Flutter 3.24.5、Rust 1.75、LLVM 15、vcpkg。
- 編譯指令：
  ```cmd
  python build.py --portable --flutter --skip-portable-pack --hwcodec --vram
  ```

### 2. Ubuntu 本機編譯：
- 必備環境：Ubuntu 20.04/22.04、Flutter 3.24.5、Rust 1.75、系統依賴（`libgtk-3-dev`, `libgstreamer1.0-dev` 等）。
- 編譯指令：
  ```bash
  python3 ./build.py --flutter --hwcodec --unix-file-copy-paste
  ```
  輸出：`rustdesk-1.5.1-x86_64.deb`

### 3. Mac MINI 實體機編譯（M1 / M2 / M3 / M4）：
- 必備環境：macOS、Xcode、Command Line Tools、Flutter 3.24.5、Rust 1.81、Homebrew (`create-dmg`, `llvm`, `pkg-config`)。
- 編譯指令：
  ```bash
  ./build.py --flutter --hwcodec --unix-file-copy-paste --screencapturekit
  create-dmg rustdesk-1.5.1-aarch64.dmg ./flutter/build/macos/Build/Products/Release/RustDesk.app
  ```
  輸出：`rustdesk-1.5.1-aarch64.dmg`
