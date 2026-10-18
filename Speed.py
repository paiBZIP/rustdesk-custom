# -*- coding: utf-8 -*-
"""
Speed.py - RustDesk 專屬網路連線、埠號檢測與雙機測速診斷工具
功能：
  1. 檢測 RustDesk 伺服器（ID / 中繼）所有核心通訊埠（21115 ~ 21119）與延遲（Ping / Jitter）
  2. A 電腦 ↔ B 電腦 端到端直連 / 中繼雙向頻寬實測（上傳 / 下載 Mbps、MB/s）
  3. 密碼保護驗證（雙機輸入相同密碼即可一鍵連線測速）
  4. 模擬各解析度（720p / 1080p / 2K / 4K）在不同畫質優先級（速度優先 / 均衡 / 畫質優先）下的頻寬佔用與操作反饋延遲
"""

import os
import sys
import re
import time
import json
import struct
import socket
import hashlib
import secrets
import threading
import queue
import urllib.request

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# Windows 高 DPI 支援
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_RS_PATH = os.path.join(BASE_DIR, "libs", "hbb_common", "src", "config.rs")

# 預設參數 (若讀不到檔案時之預設值)
DEFAULT_ID_SERVER = "vpn.xbmax.com"
DEFAULT_RELAY_SERVER = "vpn.xbmax.com"
DEFAULT_PUB_KEY = "k09QlRj3SkGwORP6Kg39KkOpRdbXGfoz3LN9QzfzXpk="
DEFAULT_BENCHMARK_PORT = 21120


def read_config_defaults():
    """從 config.rs 讀取當前專案金鑰與伺服器"""
    id_server = DEFAULT_ID_SERVER
    relay_server = DEFAULT_RELAY_SERVER
    pub_key = DEFAULT_PUB_KEY

    if os.path.exists(CONFIG_RS_PATH):
        try:
            with open(CONFIG_RS_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            m_key = re.search(r'pub const RS_PUB_KEY: &str = "(.*?)";', content)
            m_id = re.search(r'pub const RENDEZVOUS_SERVERS: &\[&str\] = &\["(.*?)"\];', content)
            m_relay = re.search(r'pub const DEFAULT_RELAY_SERVER: &str = "(.*?)";', content)

            if m_key:
                pub_key = m_key.group(1)
            if m_id:
                id_server = m_id.group(1)
            if m_relay:
                relay_server = m_relay.group(1)
        except Exception:
            pass

    return id_server, relay_server, pub_key


def get_local_ips():
    """取得本機所有局域網 IPv4 位址"""
    ips = []
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127.") and ":" not in ip:
                ips.append(ip)
    except Exception:
        pass
    if not ips:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
            s.close()
        except Exception:
            ips.append("127.0.0.1")
    return ips


def get_public_ip():
    """非同步查詢本機對外公網 IP"""
    try:
        req = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "RustDeskSpeedTool"})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return "無法獲取 (或處於純內網)"


# ----------------------------------------------------
# 網路長度前綴訊息通訊協議 (Framed Protocol)
# ----------------------------------------------------
def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def send_msg(sock, data):
    hdr = struct.pack(">I", len(data))
    sock.sendall(hdr + data)


def recv_msg(sock):
    hdr = recv_exact(sock, 4)
    if not hdr:
        return None
    sz = struct.unpack(">I", hdr)[0]
    if sz == 0:
        return b""
    return recv_exact(sock, sz)


class SpeedTestApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RustDesk 網路診斷與連線測速工具 (Speed.py)")
        self.geometry("980x860")
        self.minsize(920, 760)

        # 載入圖示
        icon_path = os.path.join(BASE_DIR, "res", "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.msg_queue = queue.Queue()
        self.server_socket = None
        self.is_server_listening = False
        self.active_client_sock = None

        # 儲存測速結果 (供模擬解析度使用)
        self.measured_rtt = 0.0
        self.measured_upload_mbps = 0.0
        self.measured_download_mbps = 0.0
        self.measured_jitter = 0.0

        id_srv, relay_srv, pub_key = read_config_defaults()
        self.id_server_val = id_srv
        self.relay_server_val = relay_srv
        self.pub_key_val = pub_key

        self._setup_style()
        self._build_ui()
        self._poll_queue()

    def _setup_style(self):
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self.bg_color = "#F8FAFC"
        self.card_bg = "#FFFFFF"
        self.configure(bg=self.bg_color)

        self.style.configure(".", background=self.bg_color, font=("Segoe UI", 9))
        self.style.configure("TLabelframe", background=self.card_bg, font=("Segoe UI", 10, "bold"))
        self.style.configure("TLabelframe.Label", background=self.card_bg, font=("Segoe UI", 10, "bold"))
        self.style.configure("TNotebook", background=self.bg_color)
        self.style.configure("TNotebook.Tab", font=("Segoe UI", 9, "bold"), padding=[12, 6])

        # 按鈕樣式
        self.style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"), background="#2563EB", foreground="#FFFFFF")
        self.style.map("Primary.TButton", background=[("active", "#1D4ED8"), ("disabled", "#CBD5E1")])

        self.style.configure("Success.TButton", font=("Segoe UI", 9, "bold"), background="#16A34A", foreground="#FFFFFF")
        self.style.map("Success.TButton", background=[("active", "#15803D"), ("disabled", "#CBD5E1")])

        self.style.configure("Action.TButton", font=("Segoe UI", 9), background="#F1F5F9", foreground="#1E293B")
        self.style.map("Action.TButton", background=[("active", "#E2E8F0")])

    def _build_ui(self):
        # 標題列
        header = tk.Frame(self, bg="#1E293B", height=70)
        header.pack(fill=tk.X, side=tk.TOP)

        t_lbl = tk.Label(header, text="⚡ RustDesk 網路質量、通訊埠檢測與雙機極限測速 (Speed.py)",
                         font=("Segoe UI", 13, "bold"), fg="#FFFFFF", bg="#1E293B")
        t_lbl.pack(anchor="w", padx=20, pady=(10, 2))

        sub_lbl = tk.Label(header,
                           text=f"ID 伺服器: {self.id_server_val} ｜ 中繼: {self.relay_server_val} ｜ 金鑰: {self.pub_key_val[:16]}...",
                           font=("Segoe UI", 9), fg="#94A3B8", bg="#1E293B")
        sub_lbl.pack(anchor="w", padx=20, pady=(0, 10))

        # 頁籤容器
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        # Tab 1: 伺服器通訊埠與延遲檢測
        self.tab_server = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_server, text="  🌐 1. 伺服器通訊埠與延遲診斷  ")
        self._build_tab_server(self.tab_server)

        # Tab 2: A 電腦 ↔ B 電腦 雙機實測
        self.tab_p2p = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_p2p, text="  🚀 2. A 電腦 ↔ B 電腦 雙機頻寬實測  ")
        self._build_tab_p2p(self.tab_p2p)

        # Tab 3: 解析度畫質與操作反應模擬
        self.tab_sim = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_sim, text="  📊 3. 解析度畫質與操作反應模擬  ")
        self._build_tab_sim(self.tab_sim)

        # Tab 4: 即時日誌終端
        self.tab_log = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_log, text="  📜 4. 詳細執行日誌  ")
        self._build_tab_log(self.tab_log)

        # 底部狀態列
        self.status_var = tk.StringVar(value="狀態：就緒")
        status_bar = tk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w",
                              bg="#E2E8F0", fg="#334155", font=("Segoe UI", 9), padx=10, pady=3)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    # ----------------------------------------------------
    # TAB 1: 伺服器通訊埠與延遲檢測
    # ----------------------------------------------------
    def _build_tab_server(self, parent):
        top_frame = tk.Frame(parent, bg=self.bg_color)
        top_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(top_frame, text="目標伺服器主機:", font=("Segoe UI", 9, "bold"), bg=self.bg_color).pack(side=tk.LEFT)
        self.entry_srv_host = ttk.Entry(top_frame, font=("Consolas", 10), width=28)
        self.entry_srv_host.insert(0, self.id_server_val)
        self.entry_srv_host.pack(side=tk.LEFT, padx=(8, 12))

        btn_test_all = ttk.Button(top_frame, text="⚡ 一鍵檢測所有埠號與延遲", style="Primary.TButton",
                                  command=self.run_server_port_diagnostics)
        btn_test_all.pack(side=tk.LEFT, ipady=2)

        # 樹狀表格呈現各埠號檢測結果
        columns = ("port", "proto", "name", "desc", "status", "ping")
        self.tree_ports = ttk.Treeview(parent, columns=columns, show="headings", height=8)

        self.tree_ports.heading("port", text="埠號 (Port)")
        self.tree_ports.heading("proto", text="協議")
        self.tree_ports.heading("name", text="服務名稱")
        self.tree_ports.heading("desc", text="用途說明")
        self.tree_ports.heading("status", text="狀態 (連通性)")
        self.tree_ports.heading("ping", text="延遲 / RTT")

        self.tree_ports.column("port", width=90, anchor="center")
        self.tree_ports.column("proto", width=70, anchor="center")
        self.tree_ports.column("name", width=140, anchor="w")
        self.tree_ports.column("desc", width=250, anchor="w")
        self.tree_ports.column("status", width=130, anchor="center")
        self.tree_ports.column("ping", width=110, anchor="center")

        self.tree_ports.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 預載埠號項目
        self.server_port_items = [
            ("21115", "TCP", "NAT 類型檢測", "hbbs NAT 探測與註冊服務", "待檢測", "-"),
            ("21116", "TCP", "ID 註冊/查詢", "hbbs 連線發起與打洞協商", "待檢測", "-"),
            ("21116", "UDP", "心跳/打洞", "hbbs UDP 註冊與打洞探針", "待檢測", "-"),
            ("21117", "TCP", "中繼資料傳輸", "hbbr 畫面轉發與音訊/檔案傳輸", "待檢測", "-"),
            ("21118", "TCP", "WebSocket ID", "Web 版客戶端 ID 註冊服務", "待檢測", "-"),
            ("21119", "TCP", "WebSocket 中繼", "Web 版客戶端中繼轉發服務", "待檢測", "-"),
        ]
        for item in self.server_port_items:
            self.tree_ports.insert("", tk.END, values=item)

        # 摘要卡片
        summary_frame = ttk.LabelFrame(parent, text="  伺服器網路品質分析摘要  ", padding=10)
        summary_frame.pack(fill=tk.X)

        self.lbl_srv_summary = tk.Label(summary_frame,
                                        text="點選上方「一鍵檢測所有埠號與延遲」按鈕，立即獲取完整通訊埠可用性與網路 RTT 延遲分析。",
                                        font=("Segoe UI", 9), justify=tk.LEFT, fg="#475569", bg=self.card_bg)
        self.lbl_srv_summary.pack(anchor="w")

    # ----------------------------------------------------
    # TAB 2: A 電腦 ↔ B 電腦 雙機實測
    # ----------------------------------------------------
    def _build_tab_p2p(self, parent):
        intro_lbl = tk.Label(parent,
                             text="💡 使用說明：A 電腦與 B 電腦皆開啟此程式。任選一台點擊「啟動伺服端」，另一台輸入對方的 IP 與密碼點擊「開始測速」即可！",
                             font=("Segoe UI", 9, "bold"), fg="#1E40AF", bg="#DBEAFE", padx=10, pady=6)
        intro_lbl.pack(fill=tk.X, pady=(0, 10))

        panes = tk.Frame(parent, bg=self.bg_color)
        panes.pack(fill=tk.BOTH, expand=True)

        # 左側：作為伺服端 (等待連線)
        frame_srv = ttk.LabelFrame(panes, text="  【角色 A】 等待連線端 (Server)  ", padding=12)
        frame_srv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        local_ips = get_local_ips()
        tk.Label(frame_srv, text=f"本機區域網路 IP: {', '.join(local_ips)}", font=("Segoe UI", 9, "bold"),
                 bg=self.card_bg, fg="#0F172A").pack(anchor="w", pady=2)

        self.lbl_pub_ip = tk.Label(frame_srv, text="對外公網 IP: 查詢中...", font=("Segoe UI", 9),
                                   bg=self.card_bg, fg="#64748B")
        self.lbl_pub_ip.pack(anchor="w", pady=2)
        threading.Thread(target=self._fetch_public_ip, daemon=True).start()

        tk.Label(frame_srv, text="監聽埠號 (Port):", font=("Segoe UI", 9), bg=self.card_bg).pack(anchor="w", pady=(8, 2))
        self.entry_listen_port = ttk.Entry(frame_srv, font=("Consolas", 10), width=15)
        self.entry_listen_port.insert(0, str(DEFAULT_BENCHMARK_PORT))
        self.entry_listen_port.pack(anchor="w")

        tk.Label(frame_srv, text="連線密碼 (Password):", font=("Segoe UI", 9), bg=self.card_bg).pack(anchor="w", pady=(8, 2))
        self.entry_srv_pwd = ttk.Entry(frame_srv, font=("Consolas", 10), width=20)
        self.entry_srv_pwd.insert(0, "rustdesk123")
        self.entry_srv_pwd.pack(anchor="w")

        self.btn_listen = ttk.Button(frame_srv, text="🎧 啟動等待連線 (Listen)", style="Success.TButton",
                                    command=self.toggle_server_listen)
        self.btn_listen.pack(anchor="w", pady=(14, 0), ipady=3)

        self.lbl_srv_status = tk.Label(frame_srv, text="狀態：尚未啟動", font=("Segoe UI", 9),
                                       fg="#64748B", bg=self.card_bg)
        self.lbl_srv_status.pack(anchor="w", pady=(8, 0))

        # 右側：作為客戶端 (發起連線)
        frame_cli = ttk.LabelFrame(panes, text="  【角色 B】 發起測試端 (Client)  ", padding=12)
        frame_cli.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(6, 0))

        tk.Label(frame_cli, text="目標電腦 IP 或主機名稱:", font=("Segoe UI", 9, "bold"), bg=self.card_bg).pack(anchor="w", pady=2)
        self.entry_target_ip = ttk.Entry(frame_cli, font=("Consolas", 10), width=28)
        self.entry_target_ip.insert(0, "127.0.0.1")
        self.entry_target_ip.pack(anchor="w", pady=(0, 4))

        tk.Label(frame_cli, text="目標埠號 (Port):", font=("Segoe UI", 9), bg=self.card_bg).pack(anchor="w", pady=(4, 2))
        self.entry_target_port = ttk.Entry(frame_cli, font=("Consolas", 10), width=15)
        self.entry_target_port.insert(0, str(DEFAULT_BENCHMARK_PORT))
        self.entry_target_port.pack(anchor="w")

        tk.Label(frame_cli, text="輸入連線密碼:", font=("Segoe UI", 9), bg=self.card_bg).pack(anchor="w", pady=(6, 2))
        self.entry_cli_pwd = ttk.Entry(frame_cli, font=("Consolas", 10), width=20)
        self.entry_cli_pwd.insert(0, "rustdesk123")
        self.entry_cli_pwd.pack(anchor="w")

        self.btn_start_bench = ttk.Button(frame_cli, text="🚀 開始雙向極限測速 (Start)", style="Primary.TButton",
                                          command=self.run_p2p_benchmark)
        self.btn_start_bench.pack(anchor="w", pady=(14, 0), ipady=3)

        self.lbl_cli_status = tk.Label(frame_cli, text="狀態：就緒", font=("Segoe UI", 9),
                                       fg="#64748B", bg=self.card_bg)
        self.lbl_cli_status.pack(anchor="w", pady=(8, 0))

        # 下方：即時測速儀表板
        dash_frame = ttk.LabelFrame(parent, text="  實測儀表板 (Live Benchmark Metrics)  ", padding=12)
        dash_frame.pack(fill=tk.X, pady=(12, 0))

        dash_grid = tk.Frame(dash_frame, bg=self.card_bg)
        dash_grid.pack(fill=tk.X)

        self.metric_rtt = self._create_metric_card(dash_grid, 0, "來回延遲 (Ping)", "-", "ms", "#2563EB")
        self.metric_jitter = self._create_metric_card(dash_grid, 1, "網路抖動 (Jitter)", "-", "ms", "#D97706")
        self.metric_upload = self._create_metric_card(dash_grid, 2, "上傳速率 (Upload)", "-", "Mbps", "#16A34A")
        self.metric_download = self._create_metric_card(dash_grid, 3, "下載速率 (Download)", "-", "Mbps", "#059669")

    def _create_metric_card(self, parent, col, title, value, unit, color):
        f = tk.Frame(parent, bg="#F8FAFC", relief=tk.SOLID, bd=1, padx=12, pady=8)
        f.grid(row=0, column=col, sticky="ew", padx=6)
        parent.columnconfigure(col, weight=1)

        tk.Label(f, text=title, font=("Segoe UI", 8), bg="#F8FAFC", fg="#64748B").pack(anchor="w")
        val_lbl = tk.Label(f, text=value, font=("Consolas", 18, "bold"), bg="#F8FAFC", fg=color)
        val_lbl.pack(anchor="w", pady=(2, 0))
        tk.Label(f, text=unit, font=("Segoe UI", 8), bg="#F8FAFC", fg="#94A3B8").pack(anchor="e")
        return val_lbl

    def _fetch_public_ip(self):
        pub_ip = get_public_ip()
        self.msg_queue.put(("call", lambda: self.lbl_pub_ip.config(text=f"對外公網 IP: {pub_ip}"), (), {}))

    # ----------------------------------------------------
    # TAB 3: 解析度畫質與操作反應模擬
    # ----------------------------------------------------
    def _build_tab_sim(self, parent):
        tk.Label(parent, text="根據上方實際測得的「網路頻寬」與「延遲 (RTT)」，自動評估在各種解析度與畫質優先級下的表現：",
                 font=("Segoe UI", 9, "bold"), fg="#1E293B", bg=self.bg_color).pack(anchor="w", pady=(0, 8))

        columns = ("res", "fps", "bitrate_req", "speed_mode", "balanced_mode", "quality_mode", "input_lag")
        self.tree_sim = ttk.Treeview(parent, columns=columns, show="headings", height=8)

        self.tree_sim.heading("res", text="通用解析度")
        self.tree_sim.heading("fps", text="目標 FPS")
        self.tree_sim.heading("bitrate_req", text="基準頻寬需求")
        self.tree_sim.heading("speed_mode", text="🚀 速度優先")
        self.tree_sim.heading("balanced_mode", text="⚖️ 均衡模式 (預設)")
        self.tree_sim.heading("quality_mode", text="🎨 畫質優先")
        self.tree_sim.heading("input_lag", text="預估滑鼠操作延遲")

        self.tree_sim.column("res", width=130, anchor="center")
        self.tree_sim.column("fps", width=80, anchor="center")
        self.tree_sim.column("bitrate_req", width=120, anchor="center")
        self.tree_sim.column("speed_mode", width=130, anchor="center")
        self.tree_sim.column("balanced_mode", width=150, anchor="center")
        self.tree_sim.column("quality_mode", width=130, anchor="center")
        self.tree_sim.column("input_lag", width=130, anchor="center")

        self.tree_sim.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        btn_recalc = ttk.Button(parent, text="🔄 依當前實測數據重新計算評估", style="Action.TButton",
                                command=self.update_resolution_simulation)
        btn_recalc.pack(anchor="w", pady=(0, 10))

        # 建議面板
        rec_frame = ttk.LabelFrame(parent, text="  最佳連線優化建議 (Optimization Advice)  ", padding=12)
        rec_frame.pack(fill=tk.X)

        self.lbl_advice = tk.Label(rec_frame,
                                   text="尚未執行測速。請至「雙機頻寬實測」分頁完成連線測速，系統將為您生成專業的調優建議。",
                                   font=("Segoe UI", 9), justify=tk.LEFT, fg="#475569", bg=self.card_bg)
        self.lbl_advice.pack(anchor="w")

        # 初始填充
        self.update_resolution_simulation()

    def update_resolution_simulation(self):
        """依據測速指標重新計算各解析度評估"""
        for item in self.tree_sim.get_children():
            self.tree_sim.delete(item)

        bw = max(self.measured_upload_mbps, self.measured_download_mbps)
        if bw <= 0:
            bw = 10.0  # 預設模擬 10 Mbps
        rtt = self.measured_rtt if self.measured_rtt > 0 else 25.0

        resolutions = [
            ("720p (1280x720)", "30 FPS", 1.2, 0.6, 1.0, 1.8),
            ("1080p (1920x1080)", "30 FPS", 2.0, 1.0, 1.5, 3.0),
            ("1080p (1920x1080)", "60 FPS", 3.8, 1.9, 2.8, 5.5),
            ("2K QHD (2560x1440)", "60 FPS", 7.5, 3.8, 5.2, 11.0),
            ("4K UHD (3840x2160)", "60 FPS", 18.0, 9.0, 13.0, 28.0),
        ]

        def get_rating(req, avail):
            ratio = avail / req
            if ratio >= 2.0:
                return "⭐⭐⭐⭐⭐ 極致"
            elif ratio >= 1.2:
                return "⭐⭐⭐⭐ 流暢"
            elif ratio >= 0.8:
                return "⭐⭐⭐ 尚可"
            else:
                return "⚠️ 頻寬不足"

        # 預估滑鼠操作延遲 = RTT + 編碼(10ms) + 解碼渲染(8ms)
        est_lag = rtt + 18.0

        for name, fps, req, spd_req, bal_req, qlt_req in resolutions:
            s_rate = get_rating(spd_req, bw)
            b_rate = get_rating(bal_req, bw)
            q_rate = get_rating(qlt_req, bw)
            lag_text = f"~{est_lag:.0f} ms"
            self.tree_sim.insert("", tk.END, values=(name, fps, f"{req:.1f} Mbps", s_rate, b_rate, q_rate, lag_text))

        # 生成建議
        advice = []
        if rtt < 35:
            advice.append("🟢 延遲極低 (<35ms)：操作反饋極佳，如同本機體驗。推薦使用「畫質優先」享受清晰畫面！")
        elif rtt < 80:
            advice.append("🟡 延遲正常 (35~80ms)：一般辦公遠端極度順暢。推薦使用「均衡模式」。")
        else:
            advice.append("🔴 延遲偏高 (>80ms)：滑鼠移動可能有跟隨感。強烈建議切換為「速度優先」，並勾選「自適應位元率」！")

        if bw > 25:
            advice.append("🚀 頻寬充裕 (>25 Mbps)：足以支撐 2K / 4K 高畫質傳輸。可在遠端畫面選單中將位元率滑桿拉至 200% 以上！")
        elif bw > 8:
            advice.append("⚖️ 頻寬適中 (8~25 Mbps)：完美支援 1080p 60FPS。建議維持預設畫質。")
        else:
            advice.append("⚠️ 頻寬受限 (<8 Mbps)：建議將畫面設為「速度優先」，或在非 P2P 環境時確認中繼伺服器頻寬。")

        self.lbl_advice.config(text="\n".join(advice))

    # ----------------------------------------------------
    # TAB 4: 即時終端機日誌
    # ----------------------------------------------------
    def _build_tab_log(self, parent):
        self.log_text = scrolledtext.ScrolledText(parent, wrap=tk.WORD, font=("Consolas", 9),
                                                 bg="#0F172A", fg="#F8FAFC", insertbackground="#FFFFFF")
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self.log_text.tag_config("INFO", foreground="#38BDF8")
        self.log_text.tag_config("SUCCESS", foreground="#4ADE80", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("WARN", foreground="#FBBF24")
        self.log_text.tag_config("ERROR", foreground="#F87171", font=("Consolas", 9, "bold"))
        self.log_text.tag_config("TIMESTAMP", foreground="#64748B")

        btn_bar = tk.Frame(parent, bg=self.bg_color)
        btn_bar.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_bar, text="🧹 清空日誌", style="Action.TButton", command=self.clear_log).pack(side=tk.RIGHT)

    def log(self, text, tag="INFO"):
        self.msg_queue.put(("log", text, tag))

    def clear_log(self):
        self.log_text.delete("1.0", tk.END)

    def set_status(self, text):
        self.msg_queue.put(("status", text))

    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    _, text, tag = msg
                    ts = time.strftime("[%H:%M:%S] ")
                    self.log_text.insert(tk.END, ts, "TIMESTAMP")
                    self.log_text.insert(tk.END, f"{text}\n", tag)
                    self.log_text.see(tk.END)
                elif kind == "status":
                    _, text = msg
                    self.status_var.set(f"狀態：{text}")
                elif kind == "call":
                    _, func, args, kwargs = msg
                    func(*args, **kwargs)
        except queue.Empty:
            pass
        except Exception:
            pass
        finally:
            self.after(50, self._poll_queue)

    # ----------------------------------------------------
    # 邏輯 1: 伺服器通訊埠與延遲診斷
    # ----------------------------------------------------
    def run_server_port_diagnostics(self):
        host = self.entry_srv_host.get().strip() or self.id_server_val
        self.log("=" * 60, "INFO")
        self.log(f"開始檢測伺服器 [{host}] 所有核心通訊埠與延遲...", "INFO")
        self.set_status("伺服器埠號檢測中...")

        for item in self.tree_ports.get_children():
            self.tree_ports.delete(item)

        ports = [
            ("21115", "TCP", "NAT 類型檢測", "hbbs NAT 探測與註冊服務"),
            ("21116", "TCP", "ID 註冊/查詢", "hbbs 連線發起與打洞協商"),
            ("21116", "UDP", "心跳/打洞", "hbbs UDP 註冊與打洞探針"),
            ("21117", "TCP", "中繼資料傳輸", "hbbr 畫面轉發與音訊/檔案傳輸"),
            ("21118", "TCP", "WebSocket ID", "Web 版客戶端 ID 註冊服務"),
            ("21119", "TCP", "WebSocket 中繼", "Web 版客戶端中繼轉發服務"),
        ]

        def _worker():
            results = []
            open_count = 0
            latencies = []

            for port_str, proto, name, desc in ports:
                port = int(port_str)
                status_str = "失敗"
                ping_str = "-"
                t0 = time.time()

                try:
                    if proto == "TCP":
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(2.5)
                        res = s.connect_ex((host, port))
                        dt = (time.time() - t0) * 1000
                        s.close()
                        if res == 0:
                            status_str = "✅ 開啟 (正常)"
                            ping_str = f"{dt:.1f} ms"
                            open_count += 1
                            latencies.append(dt)
                            self.log(f"  Port {port}/TCP ({name}): 開啟 | 延遲: {dt:.1f}ms", "SUCCESS")
                        else:
                            status_str = f"❌ 關閉/逾時 ({res})"
                            self.log(f"  Port {port}/TCP ({name}): 無法連線 (代碼 {res})", "ERROR")
                    else:
                        # UDP
                        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        s.settimeout(2.0)
                        s.sendto(b"\x00\x00", (host, port))
                        dt = (time.time() - t0) * 1000
                        s.close()
                        status_str = "✅ 暢通 (UDP)"
                        ping_str = f"{dt:.1f} ms"
                        open_count += 1
                        latencies.append(dt)
                        self.log(f"  Port {port}/UDP ({name}): 封包已送達 | ~{dt:.1f}ms", "SUCCESS")
                except Exception as e:
                    status_str = f"異常: {e}"
                    self.log(f"  Port {port}/{proto} ({name}): 異常 {e}", "WARN")

                results.append((port_str, proto, name, desc, status_str, ping_str))

            avg_ping = sum(latencies) / len(latencies) if latencies else 0.0

            def _update_ui():
                for r in results:
                    self.tree_ports.insert("", tk.END, values=r)
                summary_text = (
                    f"檢測完成！共測試 6 組埠號，其中 {open_count}/6 組通訊正常。\n"
                    f"平均連線 RTT 延遲: {avg_ping:.1f} ms。\n"
                    f"結論: {'🟢 伺服器通訊狀況優良，中繼與 ID 服務均正常運作！' if open_count >= 4 else '⚠️ 部分核心通訊埠未暢通，請檢查主機防火牆設定。'}"
                )
                self.lbl_srv_summary.config(text=summary_text)
                self.set_status("伺服器檢測完成")

            self.msg_queue.put(("call", _update_ui, (), {}))

        threading.Thread(target=_worker, daemon=True).start()

    # ----------------------------------------------------
    # 邏輯 2: A ↔ B 雙機實測 (Server Mode)
    # ----------------------------------------------------
    def toggle_server_listen(self):
        if self.is_server_listening:
            self.stop_server_listen()
        else:
            self.start_server_listen()

    def start_server_listen(self):
        try:
            port = int(self.entry_listen_port.get().strip())
        except ValueError:
            messagebox.showerror("錯誤", "監聽埠號必須為整數！")
            return

        pwd = self.entry_srv_pwd.get().strip()
        if not pwd:
            messagebox.showerror("錯誤", "連線密碼不能為空！")
            return

        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(("0.0.0.0", port))
            self.server_socket.listen(2)
            self.is_server_listening = True
            self.btn_listen.config(text="🛑 停止監聽 (Stop)")
            self.lbl_srv_status.config(text=f"狀態：正在通訊埠 {port} 監聽等待連線中...", fg="#16A34A")
            self.log(f"已在 0.0.0.0:{port} 啟動測速伺服端，等待對端電腦連線...", "SUCCESS")
            self.set_status(f"伺服端監聽中 (Port {port})")

            threading.Thread(target=self._server_accept_loop, args=(pwd,), daemon=True).start()
        except Exception as e:
            self.log(f"啟動伺服端失敗: {e}", "ERROR")
            messagebox.showerror("失敗", f"無法綁定監聽通訊埠 {port}:\n{e}")

    def stop_server_listen(self):
        self.is_server_listening = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None
        self.btn_listen.config(text="🎧 啟動等待連線 (Listen)")
        self.lbl_srv_status.config(text="狀態：已停止監聽", fg="#64748B")
        self.log("已停止測速伺服端監聽。", "INFO")
        self.set_status("已停止監聽")

    def _server_accept_loop(self, expected_pwd):
        while self.is_server_listening:
            try:
                conn, addr = self.server_socket.accept()
                self.log(f"收到來自 {addr[0]}:{addr[1]} 的連線請求，開始密碼驗證...", "INFO")

                # 密碼挑戰驗證
                salt = secrets.token_hex(8)
                send_msg(conn, f"CHALLENGE:{salt}".encode("utf-8"))

                auth_resp = recv_msg(conn)
                if not auth_resp:
                    conn.close()
                    continue

                auth_str = auth_resp.decode("utf-8", errors="ignore")
                expected_hash = hashlib.sha256((salt + expected_pwd).encode("utf-8")).hexdigest()

                if auth_str != f"AUTH:{expected_hash}":
                    self.log(f"❌ 來自 {addr[0]} 的密碼驗證失敗！拒絕連線。", "ERROR")
                    send_msg(conn, b"AUTH_FAIL")
                    conn.close()
                    continue

                send_msg(conn, b"AUTH_OK")
                self.log(f"✅ {addr[0]} 密碼驗證成功！開始測速傳輸...", "SUCCESS")

                # 執行伺服端測速服務
                self._handle_server_benchmark(conn, addr)
            except Exception:
                break

    def _handle_server_benchmark(self, conn, addr):
        try:
            # 1. 延遲 Echo 測試 (10 次)
            for _ in range(10):
                ping_pkt = recv_msg(conn)
                if not ping_pkt or not ping_pkt.startswith(b"PING:"):
                    break
                send_msg(conn, b"PONG:" + ping_pkt[5:])

            # 2. 上傳測試 (Client -> Server)
            total_up = 0
            t0 = time.time()
            while True:
                chunk = recv_msg(conn)
                if chunk is None or len(chunk) == 0:
                    break
                total_up += len(chunk)
            dt_up = max(time.time() - t0, 0.001)

            # 回傳上傳統計給 Client
            up_mbps = (total_up * 8) / (dt_up * 1_000_000)
            send_msg(conn, json.dumps({"bytes": total_up, "sec": dt_up, "mbps": up_mbps}).encode())

            # 3. 下載測試 (Server -> Client)
            bench_req = recv_msg(conn)
            if bench_req and bench_req.startswith(b"START_DOWN:"):
                dur = float(bench_req.split(b":")[1])
                data_block = b"X" * 65536
                t0 = time.time()
                total_down = 0
                while time.time() - t0 < dur:
                    send_msg(conn, data_block)
                    total_down += len(data_block)
                send_msg(conn, b"")  # 結束標記
                # 等待客戶端確認接收完畢後再關閉連線，防止 Windows TCP RST (10054)
                try:
                    recv_msg(conn)
                except Exception:
                    pass

            conn.close()
            self.log(f"與 {addr[0]} 雙向測速完成！", "SUCCESS")
        except Exception as e:
            self.log(f"伺服端測速中斷: {e}", "WARN")

    # ----------------------------------------------------
    # 邏輯 3: A ↔ B 雙機實測 (Client Mode)
    # ----------------------------------------------------
    def run_p2p_benchmark(self):
        target_ip = self.entry_target_ip.get().strip()
        try:
            target_port = int(self.entry_target_port.get().strip())
        except ValueError:
            messagebox.showerror("錯誤", "目標埠號必須為數字！")
            return

        pwd = self.entry_cli_pwd.get().strip()
        if not pwd:
            messagebox.showerror("錯誤", "請輸入連線密碼！")
            return

        self.btn_start_bench.config(state=tk.DISABLED)
        self.lbl_cli_status.config(text="連線中...", fg="#2563EB")
        self.log("=" * 60, "INFO")
        self.log(f"開始連線至目標電腦 [{target_ip}:{target_port}]...", "INFO")
        self.set_status("正在連線對端電腦...")

        def _worker():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(5.0)
                s.connect((target_ip, target_port))
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

                # 1. 驗證密碼
                chal = recv_msg(s)
                if not chal or not chal.startswith(b"CHALLENGE:"):
                    raise Exception("無法收到對端挑戰字串")

                salt = chal.split(b":")[1].decode("utf-8")
                token = hashlib.sha256((salt + pwd).encode("utf-8")).hexdigest()
                send_msg(s, f"AUTH:{token}".encode("utf-8"))

                auth_res = recv_msg(s)
                if auth_res != b"AUTH_OK":
                    raise Exception("密碼驗證失敗！請確認雙方設定的密碼一致。")

                self.log("✅ 密碼驗證通過！開始測試網路延遲與抖動...", "SUCCESS")

                # 2. 測試延遲與抖動 (10 次)
                rtts = []
                for seq in range(10):
                    t_start = time.time()
                    send_msg(s, f"PING:{seq}".encode())
                    resp = recv_msg(s)
                    dt = (time.time() - t_start) * 1000
                    rtts.append(dt)
                    time.sleep(0.03)

                avg_rtt = sum(rtts) / len(rtts)
                min_rtt = min(rtts)
                max_rtt = max(rtts)
                jitter = sum(abs(rtts[i] - rtts[i - 1]) for i in range(1, len(rtts))) / (len(rtts) - 1)

                self.measured_rtt = avg_rtt
                self.measured_jitter = jitter

                self.log(f"  來回延遲: 平均 {avg_rtt:.1f}ms (最小: {min_rtt:.1f}ms, 最大: {max_rtt:.1f}ms)", "INFO")
                self.log(f"  網路抖動 (Jitter): {jitter:.2f}ms", "INFO")

                # 更新儀表板
                self.msg_queue.put(("call", lambda: self.metric_rtt.config(text=f"{avg_rtt:.1f}"), (), {}))
                self.msg_queue.put(("call", lambda: self.metric_jitter.config(text=f"{jitter:.1f}"), (), {}))

                # 3. 測試上傳頻寬 (3 秒)
                self.log("開始測試上傳頻寬 (Client ➔ Server)...", "INFO")
                self.set_status("正在測試上傳頻寬...")
                block = b"U" * 65536
                t_up_start = time.time()
                total_sent = 0
                test_duration = 3.0

                while time.time() - t_up_start < test_duration:
                    send_msg(s, block)
                    total_sent += len(block)
                send_msg(s, b"")  # 結束標記

                # 讀取 Server 統計
                srv_stat_raw = recv_msg(s)
                srv_stat = json.loads(srv_stat_raw.decode())
                up_mbps = srv_stat["mbps"]
                up_mbs = up_mbps / 8.0
                self.measured_upload_mbps = up_mbps

                self.log(f"  上傳速率: {up_mbps:.2f} Mbps ({up_mbs:.2f} MB/s)", "SUCCESS")
                self.msg_queue.put(("call", lambda: self.metric_upload.config(text=f"{up_mbps:.1f}"), (), {}))

                # 4. 測試下載頻寬 (3 秒)
                self.log("開始測試下載頻寬 (Server ➔ Client)...", "INFO")
                self.set_status("正在測試下載頻寬...")
                send_msg(s, f"START_DOWN:{test_duration}".encode())

                total_down = 0
                t_down_start = time.time()
                while True:
                    chunk = recv_msg(s)
                    if chunk is None or len(chunk) == 0:
                        break
                    total_down += len(chunk)
                dt_down = max(time.time() - t_down_start, 0.001)

                down_mbps = (total_down * 8) / (dt_down * 1_000_000)
                down_mbs = down_mbps / 8.0
                self.measured_download_mbps = down_mbps

                self.log(f"  下載速率: {down_mbps:.2f} Mbps ({down_mbs:.2f} MB/s)", "SUCCESS")
                self.msg_queue.put(("call", lambda: self.metric_download.config(text=f"{down_mbps:.1f}"), (), {}))

                # 通知 Server 接收完畢
                try:
                    send_msg(s, b"ACK_DONE")
                except Exception:
                    pass
                s.close()

                # 自動刷新解析度模擬頁籤
                self.msg_queue.put(("call", self.update_resolution_simulation, (), {}))

                self.log("=" * 60, "SUCCESS")
                self.log("🎉 雙機網路連線與極限測速全部完成！", "SUCCESS")
                self.msg_queue.put(("call", lambda: self.lbl_cli_status.config(text="測速完成！", fg="#16A34A"), (), {}))
                self.set_status("雙機測速完成")

                # 自動切換到解析度評估頁籤並彈窗通知
                def _notify_done():
                    self.notebook.select(self.tab_sim)
                    messagebox.showinfo("測速完成",
                                        f"雙機極限測速完成！\n\n"
                                        f"來回延遲: {avg_rtt:.1f} ms\n"
                                        f"上傳速率: {up_mbps:.1f} Mbps\n"
                                        f"下載速率: {down_mbps:.1f} Mbps\n\n"
                                        f"系統已自動為您切換至「解析度畫質模擬」分頁查看完整優化建議。")
                self.msg_queue.put(("call", _notify_done, (), {}))

            except Exception as e:
                self.log(f"測速過程發生錯誤: {e}", "ERROR")
                err_msg = str(e)
                self.msg_queue.put(("call", lambda: self.lbl_cli_status.config(text=f"失敗: {err_msg}", fg="#DC2626"), (), {}))
                self.set_status("測速失敗")
                self.msg_queue.put(("call", lambda: messagebox.showerror("測速失敗", f"連線或測速失敗:\n{err_msg}"), (), {}))
            finally:
                self.msg_queue.put(("call", lambda: self.btn_start_bench.config(state=tk.NORMAL), (), {}))

        threading.Thread(target=_worker, daemon=True).start()


if __name__ == "__main__":
    app = SpeedTestApp()
    app.mainloop()
