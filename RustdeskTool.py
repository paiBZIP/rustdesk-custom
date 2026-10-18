# -*- coding: utf-8 -*-
"""
RustdeskTool - RustDesk 客戶端客製化管理工具
功能：
  1. 快速查看 / 修改 Public Key（金鑰）、ID 伺服器、中繼伺服器與版本號
  2. 一鍵儲存設定並同步更新專案所有設定檔
  3. 一鍵 Commit、Push 上傳 GitHub 並自動觸發 GitHub Actions 雲端打包
  4. 即時監控 GitHub Actions 雲端編譯三平台（Windows / Ubuntu / Mac MINI）進度
  5. 打包完成後一鍵下載最新安裝包至 OUT 資料夾
"""

import os
import sys
import re
import json
import base64
import secrets
import socket
import zipfile
import tempfile
import threading
import subprocess
import webbrowser
from datetime import datetime
import urllib.request
import urllib.error

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import queue

# Windows 高 DPI 支援
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# 根目錄路徑
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_RS_PATH = os.path.join(BASE_DIR, "libs", "hbb_common", "src", "config.rs")
CARGO_TOML_PATH = os.path.join(BASE_DIR, "Cargo.toml")
PUBSPEC_YAML_PATH = os.path.join(BASE_DIR, "flutter", "pubspec.yaml")
PORTABLE_CARGO_PATH = os.path.join(BASE_DIR, "libs", "portable", "Cargo.toml")
WORKFLOW_PATH = os.path.join(BASE_DIR, ".github", "workflows", "package-custom.yml")
OUT_DIR = os.path.join(BASE_DIR, "OUT")

GITHUB_REPO = "paiBZIP/rustdesk-custom"
GITHUB_BRANCH = "main"


class NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """處理 GitHub API 轉址至 AWS S3 時剝除 Authorization 標頭"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req and "Authorization" in new_req.headers:
            del new_req.headers["Authorization"]
        return new_req


def get_git_token():
    """從 git credential helper 讀取 GitHub 認證 Token"""
    try:
        p = subprocess.Popen(
            ["git", "credential", "fill"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=BASE_DIR
        )
        out, _ = p.communicate("protocol=https\nhost=github.com\n\n", timeout=5)
        lines = dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)
        return lines.get("password", "")
    except Exception:
        return ""


class RustdeskToolApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RustDesk 客戶端客製化管理工具 v1.0")
        self.geometry("920x820")
        self.minsize(860, 720)

        # 設定圖示
        icon_path = os.path.join(BASE_DIR, "res", "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.github_token = get_git_token()
        self.monitoring_thread = None
        self.stop_monitoring_flag = False
        self.msg_queue = queue.Queue()

        self._setup_style()
        self._build_ui()
        self._poll_queue()
        self.reload_config()

    def _setup_style(self):
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        # 色系定義
        self.bg_color = "#F1F5F9"
        self.card_bg = "#FFFFFF"
        self.accent_color = "#2563EB"
        self.text_color = "#0F172A"
        self.border_color = "#E2E8F0"

        self.configure(bg=self.bg_color)

        self.style.configure(".", background=self.bg_color, foreground=self.text_color, font=("Segoe UI", 9))
        self.style.configure("Card.TFrame", background=self.card_bg, relief="flat")
        self.style.configure("TLabelframe", background=self.card_bg, foreground="#1E293B", font=("Segoe UI", 10, "bold"))
        self.style.configure("TLabelframe.Label", background=self.card_bg, foreground="#1E293B", font=("Segoe UI", 10, "bold"))

        # 按鈕樣式
        self.style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), background="#2563EB", foreground="#FFFFFF")
        self.style.map("Primary.TButton",
                       background=[("active", "#1D4ED8"), ("disabled", "#94A3B8")])

        self.style.configure("Success.TButton", font=("Segoe UI", 10, "bold"), background="#16A34A", foreground="#FFFFFF")
        self.style.map("Success.TButton",
                       background=[("active", "#15803D"), ("disabled", "#94A3B8")])

        self.style.configure("Action.TButton", font=("Segoe UI", 9), background="#F8FAFC", foreground="#1E293B")
        self.style.map("Action.TButton",
                       background=[("active", "#E2E8F0")])

    def _build_ui(self):
        # 頂部導航 / 標題列
        header_frame = tk.Frame(self, bg="#1E293B", height=70)
        header_frame.pack(fill=tk.X, side=tk.TOP)

        title_lbl = tk.Label(header_frame, text="⚡ RustDesk 客戶端客製化管理工具",
                             font=("Segoe UI", 14, "bold"), fg="#FFFFFF", bg="#1E293B")
        title_lbl.pack(anchor="w", padx=20, pady=(12, 2))

        sub_lbl = tk.Label(header_frame,
                           text=f"快速修改 Public Key 與伺服器設定 ｜ 一鍵 GitHub 雲端編譯 (Windows / Ubuntu / Mac) ｜ 倉庫: {GITHUB_REPO} ({GITHUB_BRANCH})",
                           font=("Segoe UI", 9), fg="#94A3B8", bg="#1E293B")
        sub_lbl.pack(anchor="w", padx=20, pady=(0, 10))

        # 主滾動或容器
        main_container = tk.Frame(self, bg=self.bg_color)
        main_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=10)

        # ----------------------------------------------------
        # 區塊 1: 伺服器與金鑰設定卡片
        # ----------------------------------------------------
        config_frame = ttk.LabelFrame(main_container, text="  核心參數設定 (Server & Key Settings)  ", padding=12)
        config_frame.pack(fill=tk.X, pady=(0, 10))

        # 網格佈局
        grid = tk.Frame(config_frame, bg=self.card_bg)
        grid.pack(fill=tk.X)

        # 1. Public Key
        lbl_key = tk.Label(grid, text="Public Key (金鑰):", font=("Segoe UI", 9, "bold"), bg=self.card_bg, fg="#334155")
        lbl_key.grid(row=0, column=0, sticky="w", pady=4)

        self.entry_key = ttk.Entry(grid, font=("Consolas", 10), width=50)
        self.entry_key.grid(row=0, column=1, sticky="ew", padx=(8, 8), pady=4)

        key_btn_frame = tk.Frame(grid, bg=self.card_bg)
        key_btn_frame.grid(row=0, column=2, sticky="w", pady=4)

        btn_copy_key = ttk.Button(key_btn_frame, text="📋 複製", width=7, style="Action.TButton", command=self.copy_key)
        btn_copy_key.pack(side=tk.LEFT, padx=2)

        btn_gen_key = ttk.Button(key_btn_frame, text="🎲 產生新金鑰", width=12, style="Action.TButton", command=self.generate_new_key)
        btn_gen_key.pack(side=tk.LEFT, padx=2)

        lbl_key_hint = tk.Label(grid, text="* 程式介面未設定金鑰時，運行時會自動套用此預設金鑰 (可維持介面乾淨空白)",
                                font=("Segoe UI", 8), fg="#64748B", bg=self.card_bg)
        lbl_key_hint.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(0, 4))

        # 2. ID 伺服器
        lbl_id = tk.Label(grid, text="ID 伺服器:", font=("Segoe UI", 9, "bold"), bg=self.card_bg, fg="#334155")
        lbl_id.grid(row=2, column=0, sticky="w", pady=4)

        self.entry_id = ttk.Entry(grid, font=("Consolas", 10), width=50)
        self.entry_id.grid(row=2, column=1, sticky="ew", padx=(8, 8), pady=4)

        btn_test_id = ttk.Button(grid, text="⚡ 測試連線 (21116)", width=18, style="Action.TButton",
                                 command=lambda: self.test_server_port(self.entry_id.get().strip(), 21116, "ID 伺服器"))
        btn_test_id.grid(row=2, column=2, sticky="w", pady=4)

        # 3. 中繼伺服器
        lbl_relay = tk.Label(grid, text="中繼伺服器 (Relay):", font=("Segoe UI", 9, "bold"), bg=self.card_bg, fg="#334155")
        lbl_relay.grid(row=3, column=0, sticky="w", pady=4)

        self.entry_relay = ttk.Entry(grid, font=("Consolas", 10), width=50)
        self.entry_relay.grid(row=3, column=1, sticky="ew", padx=(8, 8), pady=4)

        btn_test_relay = ttk.Button(grid, text="⚡ 測試連線 (21117)", width=18, style="Action.TButton",
                                    command=lambda: self.test_server_port(self.entry_relay.get().strip(), 21117, "中繼伺服器"))
        btn_test_relay.grid(row=3, column=2, sticky="w", pady=4)

        # 4. 版本號
        lbl_ver = tk.Label(grid, text="版本號 (Version):", font=("Segoe UI", 9, "bold"), bg=self.card_bg, fg="#334155")
        lbl_ver.grid(row=4, column=0, sticky="w", pady=4)

        self.entry_ver = ttk.Entry(grid, font=("Consolas", 10), width=20)
        self.entry_ver.grid(row=4, column=1, sticky="w", padx=(8, 8), pady=4)

        lbl_ver_hint = tk.Label(grid, text="* 儲存時將自動同步 Cargo.toml、pubspec.yaml 與 GitHub Actions 腳本",
                                font=("Segoe UI", 8), fg="#64748B", bg=self.card_bg)
        lbl_ver_hint.grid(row=4, column=1, sticky="e", padx=(0, 8), pady=4)

        grid.columnconfigure(1, weight=1)

        # 設定儲存/重讀按鈕列
        cfg_btn_bar = tk.Frame(config_frame, bg=self.card_bg)
        cfg_btn_bar.pack(fill=tk.X, pady=(10, 0))

        btn_reload = ttk.Button(cfg_btn_bar, text="🔄 重新載入設定", style="Action.TButton", command=self.reload_config)
        btn_reload.pack(side=tk.LEFT, padx=(0, 6))

        btn_save = ttk.Button(cfg_btn_bar, text="💾 儲存修改至本機檔案", style="Success.TButton", command=self.save_config)
        btn_save.pack(side=tk.LEFT)

        # ----------------------------------------------------
        # 區塊 2: 雲端一鍵上傳與打包
        # ----------------------------------------------------
        cloud_frame = ttk.LabelFrame(main_container, text="  雲端一鍵上傳與自動打包 (One-Click Cloud Packaging)  ", padding=12)
        cloud_frame.pack(fill=tk.X, pady=(0, 10))

        msg_frame = tk.Frame(cloud_frame, bg=self.card_bg)
        msg_frame.pack(fill=tk.X, pady=(0, 8))

        lbl_commit = tk.Label(msg_frame, text="Git Commit 說明:", font=("Segoe UI", 9, "bold"), bg=self.card_bg, fg="#334155")
        lbl_commit.pack(side=tk.LEFT)

        self.entry_commit_msg = ttk.Entry(msg_frame, font=("Segoe UI", 9))
        self.entry_commit_msg.insert(0, "更新 RustDesk 設定 (金鑰/伺服器)")
        self.entry_commit_msg.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        cloud_btns = tk.Frame(cloud_frame, bg=self.card_bg)
        cloud_btns.pack(fill=tk.X)

        self.btn_push_build = ttk.Button(cloud_btns, text="🚀 一鍵儲存並上傳 GitHub (自動觸發雲端打包)",
                                         style="Primary.TButton", command=self.one_click_push_and_build)
        self.btn_push_build.pack(side=tk.LEFT, padx=(0, 8), ipady=3)

        btn_monitor = ttk.Button(cloud_btns, text="🔍 查詢打包進度", style="Action.TButton", command=self.check_ci_status)
        btn_monitor.pack(side=tk.LEFT, padx=(0, 8))

        btn_download = ttk.Button(cloud_btns, text="📥 下載最新安裝包至 OUT", style="Action.TButton", command=self.download_latest_artifacts)
        btn_download.pack(side=tk.LEFT, padx=(0, 8))

        btn_open_out = ttk.Button(cloud_btns, text="📂 開啟 OUT 資料夾", style="Action.TButton", command=self.open_out_dir)
        btn_open_out.pack(side=tk.LEFT, padx=(0, 8))

        btn_web = ttk.Button(cloud_btns, text="🌐 開啟 GitHub Actions 網頁", style="Action.TButton",
                             command=lambda: webbrowser.open(f"https://github.com/{GITHUB_REPO}/actions"))
        btn_web.pack(side=tk.RIGHT)

        # ----------------------------------------------------
        # 區塊 3: 執行日誌終端機 (Log Console)
        # ----------------------------------------------------
        log_frame = ttk.LabelFrame(main_container, text="  即時執行日誌與狀態 (Terminal Console)  ", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, font=("Consolas", 9),
                                                 bg="#0F172A", fg="#F8FAFC", insertbackground="#FFFFFF")
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # 標籤顏色
        self.log_text.tag_config("INFO", foreground="#38BDF8")
        self.log_text.tag_config("SUCCESS", foreground="#4ADE80", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("WARN", foreground="#FBBF24")
        self.log_text.tag_config("ERROR", foreground="#F87171", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("TIMESTAMP", foreground="#64748B")

        log_bottom = tk.Frame(log_frame, bg=self.card_bg)
        log_bottom.pack(fill=tk.X, pady=(6, 0))

        btn_clear_log = ttk.Button(log_bottom, text="🧹 清空日誌", style="Action.TButton", command=self.clear_log)
        btn_clear_log.pack(side=tk.RIGHT)

        # 底部狀態列
        self.status_var = tk.StringVar(value="狀態：就緒")
        status_bar = tk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w",
                              bg="#E2E8F0", fg="#334155", font=("Segoe UI", 9), padx=10, pady=3)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    # ----------------------------------------------------
    # 執行緒安全之訊息佇列 (Thread-Safe Message Queue)
    # ----------------------------------------------------
    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    _, text, tag = msg
                    ts = datetime.now().strftime("[%H:%M:%S] ")
                    self.log_text.insert(tk.END, ts, "TIMESTAMP")
                    self.log_text.insert(tk.END, f"{text}\n", tag)
                    self.log_text.see(tk.END)
                elif kind == "status":
                    _, text = msg
                    self.status_var.set(f"狀態：{text}")
                elif kind == "btn":
                    _, btn, state = msg
                    btn.config(state=state)
                elif kind == "call":
                    _, func, args, kwargs = msg
                    func(*args, **kwargs)
        except queue.Empty:
            pass
        except Exception:
            pass
        finally:
            self.after(50, self._poll_queue)

    def log(self, text, tag="INFO"):
        self.msg_queue.put(("log", text, tag))

    def clear_log(self):
        self.log_text.delete("1.0", tk.END)

    def set_status(self, text):
        self.msg_queue.put(("status", text))

    def set_btn_state(self, btn, state):
        self.msg_queue.put(("btn", btn, state))

    def run_on_main(self, func, *args, **kwargs):
        self.msg_queue.put(("call", func, args, kwargs))

    # ----------------------------------------------------
    # 設定讀取與寫入
    # ----------------------------------------------------
    def reload_config(self):
        """讀取檔案設定並填入輸入框"""
        try:
            if not os.path.exists(CONFIG_RS_PATH):
                self.log(f"找不到配置檔案: {CONFIG_RS_PATH}", "ERROR")
                return

            with open(CONFIG_RS_PATH, "r", encoding="utf-8") as f:
                content = f.read()

            pub_key_m = re.search(r'pub const RS_PUB_KEY: &str = "(.*?)";', content)
            id_server_m = re.search(r'pub const RENDEZVOUS_SERVERS: &\[&str\] = &\["(.*?)"\];', content)
            relay_server_m = re.search(r'pub const DEFAULT_RELAY_SERVER: &str = "(.*?)";', content)

            pub_key = pub_key_m.group(1) if pub_key_m else ""
            id_server = id_server_m.group(1) if id_server_m else ""
            relay_server = relay_server_m.group(1) if relay_server_m else ""

            # 讀取版本號
            version = "1.5.1"
            if os.path.exists(CARGO_TOML_PATH):
                with open(CARGO_TOML_PATH, "r", encoding="utf-8") as f:
                    cargo_content = f.read()
                ver_m = re.search(r'(?m)^version\s*=\s*"(.*?)"', cargo_content)
                if ver_m:
                    version = ver_m.group(1)

            self.entry_key.delete(0, tk.END)
            self.entry_key.insert(0, pub_key)

            self.entry_id.delete(0, tk.END)
            self.entry_id.insert(0, id_server)

            self.entry_relay.delete(0, tk.END)
            self.entry_relay.insert(0, relay_server)

            self.entry_ver.delete(0, tk.END)
            self.entry_ver.insert(0, version)

            self.log("成功從本地專案讀取設定！", "SUCCESS")
            self.set_status("本地設定載入完成")
        except Exception as e:
            self.log(f"讀取設定發生錯誤: {e}", "ERROR")

    def save_config(self, show_msg=True):
        """儲存設定至所有相關檔案"""
        pub_key = self.entry_key.get().strip()
        id_server = self.entry_id.get().strip()
        relay_server = self.entry_relay.get().strip()
        version = self.entry_ver.get().strip()

        if not pub_key:
            messagebox.showwarning("警告", "Public Key 不能為空！")
            return False
        if not id_server:
            messagebox.showwarning("警告", "ID 伺服器不能為空！")
            return False
        if not relay_server:
            messagebox.showwarning("警告", "中繼伺服器不能為空！")
            return False
        if not version:
            messagebox.showwarning("警告", "版本號不能為空！")
            return False

        try:
            # 1. 更新 libs/hbb_common/src/config.rs
            with open(CONFIG_RS_PATH, "r", encoding="utf-8") as f:
                content = f.read()

            content = re.sub(r'pub const RS_PUB_KEY: &str = ".*?";',
                             f'pub const RS_PUB_KEY: &str = "{pub_key}";', content)
            content = re.sub(r'pub const RENDEZVOUS_SERVERS: &\[&str\] = &\[".*?"\];',
                             f'pub const RENDEZVOUS_SERVERS: &[&str] = &["{id_server}"];', content)
            content = re.sub(r'pub const DEFAULT_RELAY_SERVER: &str = ".*?";',
                             f'pub const DEFAULT_RELAY_SERVER: &str = "{relay_server}";', content)

            with open(CONFIG_RS_PATH, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            self.log(f"已更新: {os.path.relpath(CONFIG_RS_PATH, BASE_DIR)}", "SUCCESS")

            # 2. 更新 Cargo.toml
            if os.path.exists(CARGO_TOML_PATH):
                with open(CARGO_TOML_PATH, "r", encoding="utf-8") as f:
                    cargo = f.read()
                cargo = re.sub(r'(?m)^(\[package\][\s\S]*?^version\s*=\s*")[^"]+(")',
                               rf'\g<1>{version}\g<2>', cargo, count=1)
                with open(CARGO_TOML_PATH, "w", encoding="utf-8", newline="\n") as f:
                    f.write(cargo)
                self.log(f"已更新: {os.path.relpath(CARGO_TOML_PATH, BASE_DIR)} (v{version})", "SUCCESS")

            # 3. 更新 flutter/pubspec.yaml
            if os.path.exists(PUBSPEC_YAML_PATH):
                with open(PUBSPEC_YAML_PATH, "r", encoding="utf-8") as f:
                    pubspec = f.read()
                pubspec = re.sub(r'(?m)^version:\s*[0-9.]+(\+\d+)', rf'version: {version}\g<1>', pubspec)
                with open(PUBSPEC_YAML_PATH, "w", encoding="utf-8", newline="\n") as f:
                    f.write(pubspec)
                self.log(f"已更新: {os.path.relpath(PUBSPEC_YAML_PATH, BASE_DIR)} (v{version})", "SUCCESS")

            # 4. 更新 libs/portable/Cargo.toml
            if os.path.exists(PORTABLE_CARGO_PATH):
                with open(PORTABLE_CARGO_PATH, "r", encoding="utf-8") as f:
                    port = f.read()
                port = re.sub(r'(?m)^(\[package\][\s\S]*?^version\s*=\s*")[^"]+(")',
                              rf'\g<1>{version}\g<2>', port, count=1)
                with open(PORTABLE_CARGO_PATH, "w", encoding="utf-8", newline="\n") as f:
                    f.write(port)
                self.log(f"已更新: {os.path.relpath(PORTABLE_CARGO_PATH, BASE_DIR)} (v{version})", "SUCCESS")

            # 5. 更新 .github/workflows/package-custom.yml
            if os.path.exists(WORKFLOW_PATH):
                with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
                    workflow = f.read()
                workflow = re.sub(r'(?m)^(\s*VERSION:\s*")[^"]+(")', rf'\g<1>{version}\g<2>', workflow)
                with open(WORKFLOW_PATH, "w", encoding="utf-8", newline="\n") as f:
                    f.write(workflow)
                self.log(f"已更新: {os.path.relpath(WORKFLOW_PATH, BASE_DIR)} (VERSION: {version})", "SUCCESS")

            self.set_status("本地所有配置檔案儲存成功")
            if show_msg:
                messagebox.showinfo("成功", f"設定已成功寫入所有檔案！\n\nPublic Key: {pub_key[:12]}...\nID 伺服器: {id_server}\n中繼伺服器: {relay_server}\n版本: {version}")
            return True
        except Exception as e:
            self.log(f"儲存設定發生錯誤: {e}", "ERROR")
            messagebox.showerror("錯誤", f"儲存設定失敗:\n{e}")
            return False

    def copy_key(self):
        key = self.entry_key.get().strip()
        if key:
            self.clipboard_clear()
            self.clipboard_append(key)
            self.log(f"已將 Public Key 複製到剪貼簿", "INFO")
            messagebox.showinfo("提示", "已將 Public Key 複製到剪貼簿！")

    def generate_new_key(self):
        """產生隨機 32-byte Ed25519 Base64 金鑰"""
        if messagebox.askyesno("確認", "確定要隨機產生一組新的 Public Key（金鑰）嗎？\n注意：伺服器端若開啟金鑰驗證，兩端需保持一致。"):
            new_key = base64.b64encode(secrets.token_bytes(32)).decode("utf-8")
            self.entry_key.delete(0, tk.END)
            self.entry_key.insert(0, new_key)
            self.log(f"已產生新隨機金鑰: {new_key}", "WARN")

    def test_server_port(self, host, port, label):
        """在背景執行緒中測試伺服器端口連通性"""
        if not host:
            messagebox.showwarning("警告", f"請先填入 {label} 位址！")
            return

        def _worker():
            self.log(f"正在測試 {label} ({host}:{port}) 連線中...", "INFO")
            self.set_status(f"測試 {label} 連線中...")
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3.5)
                res = s.connect_ex((host, port))
                s.close()
                if res == 0:
                    self.log(f"✅ {label} ({host}:{port}) TCP 連線成功！伺服器運作正常。", "SUCCESS")
                    self.set_status(f"{label} 連線正常")
                else:
                    self.log(f"⚠️ {label} ({host}:{port}) 無法建立 TCP 連線 (錯誤代碼: {res})。請確認主機防火牆與服務狀態。", "WARN")
                    self.set_status(f"{label} 連線失敗 (Code {res})")
            except Exception as e:
                self.log(f"❌ 測試 {label} 發生異常: {e}", "ERROR")
                self.set_status("連線測試發生錯誤")

        threading.Thread(target=_worker, daemon=True).start()

    # ----------------------------------------------------
    # 一鍵上傳與雲端打包
    # ----------------------------------------------------
    def one_click_push_and_build(self):
        """儲存 -> Git Add -> Commit -> Push -> 啟動監看"""
        if not self.save_config(show_msg=False):
            return

        commit_msg = self.entry_commit_msg.get().strip() or "更新 RustDesk 設定"

        def _worker():
            self.set_btn_state(self.btn_push_build, tk.DISABLED)
            self.set_status("正在執行 Git Commit & Push...")
            self.log("=" * 60, "INFO")
            self.log("🚀 開始執行一鍵上傳與打包流程...", "INFO")

            try:
                # 1. git add .
                self.log("執行: git add .", "INFO")
                subprocess.run(["git", "add", "."], cwd=BASE_DIR, check=True)

                # 2. 檢查是否有變更
                status_res = subprocess.run(["git", "status", "--porcelain"], cwd=BASE_DIR, capture_output=True, text=True)
                has_changes = bool(status_res.stdout.strip())

                if has_changes:
                    self.log(f"發現程式碼變更，執行 commit: '{commit_msg}'", "INFO")
                    commit_res = subprocess.run(["git", "commit", "-m", commit_msg], cwd=BASE_DIR, capture_output=True, text=True)
                    self.log(commit_res.stdout.strip(), "INFO")
                else:
                    self.log("本機暫無新變更，直接進行 Git Push 檢查...", "WARN")

                # 3. git push origin main
                self.log(f"執行: git push origin {GITHUB_BRANCH}...", "INFO")
                push_res = subprocess.run(["git", "push", "origin", GITHUB_BRANCH], cwd=BASE_DIR, capture_output=True, text=True)

                if push_res.returncode == 0:
                    self.log("🎉 Git Push 成功！GitHub Actions 雲端打包已自動觸發 🚀", "SUCCESS")
                    self.set_status("Push 成功！已觸發雲端打包")
                    # 自動啟動即時打包狀態監控
                    self.start_monitoring_run()
                else:
                    self.log(f"Git Push 失敗:\n{push_res.stderr}", "ERROR")
                    self.set_status("Git Push 失敗")
            except Exception as e:
                self.log(f"執行上傳打包發生異常: {e}", "ERROR")
                self.set_status("上傳打包失敗")
            finally:
                self.set_btn_state(self.btn_push_build, tk.NORMAL)

        threading.Thread(target=_worker, daemon=True).start()

    def start_monitoring_run(self):
        """啟動背景監控最新 GitHub Actions 執行狀態"""
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.stop_monitoring_flag = True

        self.stop_monitoring_flag = False

        def _monitor():
            import time
            token = self.github_token or get_git_token()
            self.log("開始監控 GitHub Actions 打包進度 (每 15 秒更新一次)...", "INFO")

            last_run_id = None
            for _ in range(60):  # 最多監控 15 分鐘
                if self.stop_monitoring_flag:
                    break

                try:
                    req = urllib.request.Request(
                        f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs?per_page=1",
                        headers={"Authorization": f"Bearer {token}", "User-Agent": "RustDeskTool"}
                    )
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read().decode("utf-8"))

                    runs = data.get("workflow_runs", [])
                    if not runs:
                        time.sleep(10)
                        continue

                    run = runs[0]
                    run_id = run["id"]
                    status = run["status"]
                    conclusion = run.get("conclusion")
                    html_url = run["html_url"]

                    # 查詢各 Job 狀態
                    jobs_req = urllib.request.Request(
                        f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}/jobs",
                        headers={"Authorization": f"Bearer {token}", "User-Agent": "RustDeskTool"}
                    )
                    with urllib.request.urlopen(jobs_req, timeout=10) as resp:
                        jobs_data = json.loads(resp.read().decode("utf-8"))

                    jobs = jobs_data.get("jobs", [])
                    job_summary = []
                    for j in jobs:
                        j_name = j["name"]
                        j_status = j["status"]
                        j_conc = j.get("conclusion")
                        icon = "⏳" if j_status != "completed" else ("✅" if j_conc == "success" else "❌")
                        job_summary.append(f"{icon} {j_name}: {j_status} ({j_conc or 'run'})")

                    self.log(f"--- [雲端打包 Run #{run_id}] 總狀態: {status} ({conclusion or '執行中'}) ---", "INFO")
                    for s in job_summary:
                        self.log(f"    {s}", "INFO")

                    self.set_status(f"雲端打包中: {status} ({conclusion or '進行中'})")

                    if status == "completed":
                        if conclusion == "success":
                            self.log(f"🎉 恭喜！GitHub Actions 三平台打包已全部成功完成！", "SUCCESS")
                            self.log(f"網址: {html_url}", "SUCCESS")
                            self.set_status("雲端打包成功！可一鍵下載安裝包")
                            # 詢問是否立即下載
                            self.run_on_main(self.prompt_download_after_build)
                        else:
                            self.log(f"❌ 雲端打包結束，結果為: {conclusion}", "ERROR")
                            self.set_status(f"打包失敗 ({conclusion})")
                        break

                except Exception as e:
                    self.log(f"查詢進度時發生例外: {e}", "WARN")

                time.sleep(15)

        self.monitoring_thread = threading.Thread(target=_monitor, daemon=True)
        self.monitoring_thread.start()

    def prompt_download_after_build(self):
        if messagebox.askyesno("打包完成", "🎉 雲端打包已成功完成！\n是否立即下載最新安裝包 (Windows / Mac / Ubuntu) 至 OUT 資料夾？"):
            self.download_latest_artifacts()

    def check_ci_status(self):
        """手動觸發單次 CI 狀態查詢"""
        def _worker():
            token = self.github_token or get_git_token()
            self.log("正在向 GitHub API 查詢最新打包工作流程...", "INFO")
            self.set_status("查詢 GitHub Actions 狀態中...")
            try:
                req = urllib.request.Request(
                    f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs?per_page=3",
                    headers={"Authorization": f"Bearer {token}", "User-Agent": "RustDeskTool"}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                runs = data.get("workflow_runs", [])
                if not runs:
                    self.log("未找到任何 workflow 執行記錄。", "WARN")
                    return

                for idx, run in enumerate(runs):
                    run_id = run["id"]
                    status = run["status"]
                    conclusion = run.get("conclusion")
                    created_at = run.get("created_at")
                    url = run.get("html_url")
                    commit_title = run.get("head_commit", {}).get("message", "").splitlines()[0] if run.get("head_commit") else ""

                    tag = "SUCCESS" if conclusion == "success" else ("ERROR" if conclusion == "failure" else "INFO")
                    self.log(f"[{idx+1}] Run #{run_id} | 狀態: {status} | 結果: {conclusion} | 時間: {created_at}", tag)
                    self.log(f"    說明: {commit_title}", "INFO")
                    self.log(f"    連結: {url}", "INFO")

                self.set_status("CI 狀態查詢完成")
            except Exception as e:
                self.log(f"查詢 GitHub API 失敗: {e}", "ERROR")
                self.set_status("查詢失敗")

        threading.Thread(target=_worker, daemon=True).start()

    # ----------------------------------------------------
    # 下載打包產物至 OUT 資料夾
    # ----------------------------------------------------
    def download_latest_artifacts(self):
        """下載最新的 OUT 產物壓縮檔並解壓縮至本地 OUT 目錄"""
        def _worker():
            token = self.github_token or get_git_token()
            if not token:
                self.log("⚠️ 找不到 GitHub Token，無法透過 API 下載私人或受限產物。請開啟網頁手動下載。", "ERROR")
                messagebox.showerror("錯誤", "找不到 GitHub Token！\n請直接開啟 GitHub Actions 網頁手動下載安裝包。")
                return

            self.log("正在尋找最新已完成打包的安裝包產物 (OUT)...", "INFO")
            self.set_status("搜尋安裝包產物...")

            try:
                # 1. 取得產物清單
                req = urllib.request.Request(
                    f"https://api.github.com/repos/{GITHUB_REPO}/actions/artifacts?per_page=20",
                    headers={"Authorization": f"Bearer {token}", "User-Agent": "RustDeskTool"}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                artifacts = data.get("artifacts", [])
                target_art = None
                for a in artifacts:
                    if a["name"] == "OUT":
                        target_art = a
                        break

                if not target_art:
                    self.log("未在最近的產物中找到名為 'OUT' 的合併安裝包產物。", "WARN")
                    messagebox.showwarning("提示", "未找到名為 'OUT' 的打包產物，可能編譯尚未結束或失敗。")
                    return

                art_id = target_art["id"]
                art_size_mb = target_art["size_in_bytes"] / 1024 / 1024
                download_url = target_art["archive_download_url"]

                self.log(f"找到最新安裝包產物 (ID: {art_id}, 大小: {art_size_mb:.2f} MB)，開始下載...", "INFO")
                self.set_status(f"下載產物中 ({art_size_mb:.1f} MB)...")

                opener = urllib.request.build_opener(NoAuthRedirect)
                dl_req = urllib.request.Request(
                    download_url,
                    headers={"Authorization": f"Bearer {token}", "User-Agent": "RustDeskTool"}
                )

                # 下載至暫存檔案
                temp_zip = os.path.join(tempfile.gettempdir(), f"rustdesk_out_{art_id}.zip")
                with opener.open(dl_req, timeout=120) as resp, open(temp_zip, "wb") as f_out:
                    downloaded = 0
                    while True:
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        f_out.write(chunk)
                        downloaded += len(chunk)
                        mb = downloaded / 1024 / 1024
                        self.set_status(f"已下載: {mb:.1f} MB / {art_size_mb:.1f} MB")

                self.log(f"下載完成！正在解壓縮至: {OUT_DIR}", "SUCCESS")
                os.makedirs(OUT_DIR, exist_ok=True)

                with zipfile.ZipFile(temp_zip, "r") as z:
                    z.extractall(OUT_DIR)

                try:
                    os.remove(temp_zip)
                except Exception:
                    pass

                self.log("=" * 60, "SUCCESS")
                self.log("🎉 最新三平台安裝包已成功更新至 OUT 目錄！", "SUCCESS")
                for root, _, files in os.walk(OUT_DIR):
                    for file in files:
                        p = os.path.join(root, file)
                        sz = os.path.getsize(p) / 1024 / 1024
                        self.log(f"  📦 {file} ({sz:.2f} MB)", "SUCCESS")
                self.log("=" * 60, "SUCCESS")

                self.set_status("下載並解壓縮完成！")
                messagebox.showinfo("成功", f"最新三平台安裝包已成功下載至 OUT 目錄！\n\n點選確定將立即為您開啟 OUT 資料夾。")
                self.open_out_dir()

            except Exception as e:
                self.log(f"下載產物失敗: {e}", "ERROR")
                self.set_status("下載安裝包失敗")
                messagebox.showerror("下載失敗", f"無法下載安裝包產物:\n{e}")

        threading.Thread(target=_worker, daemon=True).start()

    def open_out_dir(self):
        """開啟 OUT 資料夾"""
        os.makedirs(OUT_DIR, exist_ok=True)
        try:
            os.startfile(OUT_DIR)
        except Exception as e:
            self.log(f"開啟資料夾失敗: {e}", "ERROR")


if __name__ == "__main__":
    app = RustdeskToolApp()
    app.mainloop()
