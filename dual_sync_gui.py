"""激光测距 + 深度相机 · 同步测定界面（自动识别设备，可直接拷到另一台电脑运行）。

启动时会自动扫描全部串口，找出真正输出距离数据的激光模块，并把设备信息
（端口、型号描述、VID/PID）与相机型号/序列号显示在顶部，不需要改代码。

功能:
    - 左侧实时显示 RealSense 彩色图与对齐后的深度伪彩图
    - 右侧实时显示激光测距值与 ROI 内深度中位数，并给出两者差值
    - 空格打点：同时记录两个传感器读数、差值、波动、同步偏差
    - 一键导出 CSV

操作:
    空格          打点记录
    Ctrl+Z        撤销上一条
    鼠标点击图像    把测量 ROI 移到点击位置（对准激光光斑）
    鼠标滚轮       调整 ROI 大小

用法:
    python dual_sync_gui.py                # 自动识别全部设备
    python dual_sync_gui.py COM6 115200    # 指定端口
    python dual_sync_gui.py --nolaser      # 只接深度相机
"""
import csv
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

WIN_SEC = 10.0
LASER_WINDOW = 0.15
IMG_W, IMG_H = 280, 210
SRC_W, SRC_H = 640, 480
ROI_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "roi_config.json")

# 一次性完成重量级模块导入。主线程与后台线程此后不再执行任何 import 语句，
# 避免争抢全局导入锁导致界面卡在首帧。
try:
    import cv2
    import numpy as np
    from PIL import Image, ImageTk
    IMAGE_DEPS_OK = True
except ImportError:
    cv2 = None
    np = None
    Image = None
    ImageTk = None
    IMAGE_DEPS_OK = False

BG = "#FFFFFF"
PANEL = "#F5F5F3"
LINE = "#D0CFC9"
C_TEXT = "#2C2C2A"
C_MUTED = "#888780"
C_ACCENT = "#A32D2D"
C_OK = "#0F6E56"
C_ROI = "#D4537E"

FONT = ("Microsoft YaHei", 10)
FONT_MID = ("Microsoft YaHei", 13)
FONT_BIG = ("Microsoft YaHei", 30)
FONT_SM = ("Microsoft YaHei", 9)
FONT_BTN = ("Microsoft YaHei", 11)


def check_deps():
    """返回缺失的依赖包名列表。"""
    missing = []
    for mod, pkg, required in [
        ("serial", "pyserial", True),
        ("cv2", "opencv-python", True),
        ("PIL", "pillow", True),
        ("numpy", "numpy", True),
        ("pyrealsense2", "pyrealsense2", False),
    ]:
        try:
            __import__(mod)
        except ImportError:
            if required:
                missing.append(pkg)
            else:
                missing.append(pkg + " (缺此项则仅激光可用)")
    return missing


class LaserWorker:
    """可随时切换端口的串口读取线程。"""

    def __init__(self, out_q):
        self.out_q = out_q
        self.ser = None
        self.thread = None
        self.stop_flag = threading.Event()
        self.port = None
        self.last_rx = 0.0
        self.connected_at = 0.0

    def start(self, port, baud):
        self.stop()
        self.stop_flag.clear()
        self.port = port
        self.thread = threading.Thread(target=self._run, args=(port, baud), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag.set()
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=0.6)
        self.thread = None

    def _run(self, port, baud):
        ser = None
        self.connected_at = time.time()
        try:
            import serial
            ser = serial.Serial(port, baud, timeout=0.2)
            ser.dtr = False
            ser.rts = False
            ser.reset_input_buffer()
            self.ser = ser
        except Exception as exc:
            self.out_q.put(("error", f"{port} 打开失败: {exc}"))
            return

        try:
            while not self.stop_flag.is_set():
                try:
                    raw = ser.readline()
                except Exception as exc:
                    self.out_q.put(("error", f"{port} 读取中断: {exc}"))
                    break
                if not raw:
                    continue
                line = raw.decode("ascii", "ignore").strip()
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) != 2:
                    continue
                try:
                    dist = int(parts[0].strip())
                    conf = int(parts[1].strip())
                except ValueError:
                    continue
                self.last_rx = time.time()
                self.out_q.put(("data", (self.last_rx, dist, conf)))
        finally:
            try:
                if ser is not None:
                    ser.close()
            except Exception:
                pass
            self.ser = None


class App:
    def __init__(self, root, port, baud, use_laser=True, demo=False):
        self.root = root
        self.baud = baud
        self.use_laser = use_laser
        self.demo = demo
        self.running = True

        self.laser_q = queue.Queue()
        self.cam_q = queue.Queue(maxsize=2)
        self.scan_q = queue.Queue()
        self.laser = LaserWorker(self.laser_q)
        self.laser_data = deque(maxlen=3000)
        self.marks = []
        self.t_start = time.time()

        self.cam_ok = False
        self.cam_msg = "未连接"
        self.cam_info = "相机: 未连接"
        self.latest_rgb = None
        self.latest_depth = None
        self.latest_ir = None
        self.latest_cam_t = None
        self.has_ir = False
        self.depth_sensor = None
        self.emitter_on = True
        self._rs = None
        self.roi_cx, self.roi_cy, self.roi_half = SRC_W // 2, SRC_H // 2, 20
        self.load_roi()
        self.scanning = False
        self.last_rescan = 0.0
        self.pump_ts = deque(maxlen=40)

        root.title("激光 + 深度相机 · 同步测定")
        root.geometry("1360x900")
        root.configure(bg=BG)
        root.minsize(1060, 760)

        self._build()

        if demo:
            threading.Thread(target=self._demo_laser, daemon=True).start()
            threading.Thread(target=self._demo_cam, daemon=True).start()
        else:
            if use_laser:
                if port:
                    self.connect_port(port)
                    self.refresh_port_list()
                else:
                    self.auto_scan()
            threading.Thread(target=self._cam_loop, daemon=True).start()

        root.bind("<space>", lambda e: self.mark())
        root.bind("<Control-z>", lambda e: self.undo())
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.pump()
        root.after(120, self._bring_to_front)

    def _build(self):
        top = tk.Frame(self.root, bg=BG, padx=16)
        top.pack(fill="x", pady=(10, 4))
        tk.Label(top, text="激光 + 深度相机 · 同步测定", font=("Microsoft YaHei", 13),
                 bg=BG, fg=C_TEXT).pack(side="left")
        self.lbl_status = tk.Label(top, text="初始化...", font=FONT_SM, bg=BG, fg=C_MUTED)
        self.lbl_status.pack(side="right")

        devbar = tk.Frame(self.root, bg=PANEL, padx=16, pady=8)
        devbar.pack(fill="x", padx=16)

        tk.Label(devbar, text="激光", font=FONT_SM, bg=PANEL, fg=C_MUTED).pack(side="left")
        self.lbl_laser_dev = tk.Label(devbar, text="正在扫描串口...", font=FONT,
                                      bg=PANEL, fg=C_TEXT)
        self.lbl_laser_dev.pack(side="left", padx=(6, 10))

        self.cmb_port = ttk.Combobox(devbar, width=8, state="readonly", font=FONT)
        self.cmb_port.pack(side="left")
        self.cmb_port.bind("<<ComboboxSelected>>", lambda e: self.connect_selected())

        tk.Button(devbar, text="重新扫描", font=FONT_SM, relief="flat", bg=BG, fg=C_TEXT,
                  command=self.auto_scan).pack(side="left", padx=(6, 0))

        tk.Button(devbar, text="重连相机", font=FONT_SM, relief="flat", bg=BG, fg=C_TEXT,
                  command=self.reconnect_cam).pack(side="right")
        self.lbl_cam_dev = tk.Label(devbar, text="相机: 连接中...", font=FONT,
                                    bg=PANEL, fg=C_TEXT)
        self.lbl_cam_dev.pack(side="right", padx=(0, 10))

        mid = tk.Frame(self.root, bg=BG, padx=16, pady=10)
        mid.pack(fill="both", expand=True)

        imgbox = tk.Frame(mid, bg=BG)
        imgbox.pack(side="left", fill="y")
        self.canvas_rgb = tk.Canvas(imgbox, width=IMG_W, height=IMG_H, bg="#1A1A1A",
                                    highlightthickness=1, highlightbackground=LINE)
        self.canvas_rgb.grid(row=0, column=0, padx=(0, 6))
        self.canvas_depth = tk.Canvas(imgbox, width=IMG_W, height=IMG_H, bg="#1A1A1A",
                                      highlightthickness=1, highlightbackground=LINE)
        self.canvas_depth.grid(row=0, column=1, padx=(0, 6))
        self.canvas_ir = tk.Canvas(imgbox, width=IMG_W, height=IMG_H, bg="#1A1A1A",
                                   highlightthickness=1, highlightbackground=LINE)
        self.canvas_ir.grid(row=0, column=2)

        tk.Label(imgbox, text="彩色（参考）", font=FONT_SM, bg=BG,
                 fg=C_MUTED).grid(row=1, column=0)
        tk.Label(imgbox, text="深度（点击设 ROI）", font=FONT_SM, bg=BG,
                 fg=C_MUTED).grid(row=1, column=1)
        tk.Label(imgbox, text="红外 · 看激光光斑", font=FONT_SM, bg=BG,
                 fg=C_ACCENT).grid(row=1, column=2)

        for c in (self.canvas_rgb, self.canvas_depth, self.canvas_ir):
            c.bind("<Button-1>", self.on_click)
            c.bind("<MouseWheel>", self.on_wheel)

        panel = tk.Frame(mid, bg=PANEL, padx=16, pady=14)
        panel.pack(side="left", fill="both", expand=True, padx=(12, 0))

        def block(title, big=False):
            tk.Label(panel, text=title, font=FONT_SM, bg=PANEL, fg=C_MUTED).pack(anchor="w")
            lbl = tk.Label(panel, text="--", font=FONT_BIG if big else FONT_MID,
                           bg=PANEL, fg=C_ACCENT if big else C_TEXT)
            lbl.pack(anchor="w", pady=(0, 8))
            return lbl

        self.lbl_laser = block("激光测距 (mm)", big=True)
        self.lbl_cam = block("相机 ROI 深度 (mm)")
        self.lbl_diff = block("两者差值 (mm)")
        self.lbl_extra = block("激光波动 / 有效像素")

        roitag = "已标定" if self.roi_loaded else "未标定"
        self.lbl_roi = tk.Label(panel, text=f"ROI ({self.roi_cx},{self.roi_cy}) "
                                            f"边长 {self.roi_half * 2 + 1}px · {roitag}",
                                font=FONT_SM, bg=PANEL, fg=C_MUTED)
        self.lbl_roi.pack(anchor="w")

        self.canvas_plot = tk.Canvas(panel, bg=BG, height=100, highlightthickness=1,
                                     highlightbackground=LINE)
        self.canvas_plot.pack(fill="x", pady=(8, 0))

        bar = tk.Frame(self.root, bg=BG, padx=16, pady=8)
        bar.pack(fill="x")
        self.btn_mark = tk.Button(bar, text="打点记录  (空格)", font=FONT_BTN, width=18,
                                  relief="flat", bg="#E1F5EE", fg=C_OK, height=2,
                                  activebackground="#9FE1CB", command=self.mark)
        self.btn_mark.pack(side="left")
        tk.Button(bar, text="撤销 (Ctrl+Z)", font=FONT, width=13, relief="flat", bg=PANEL,
                  fg=C_TEXT, command=self.undo, height=2).pack(side="left", padx=(8, 0))
        tk.Button(bar, text="导出 CSV", font=FONT, width=11, relief="flat", bg=PANEL,
                  fg=C_TEXT, command=self.export, height=2).pack(side="left", padx=(8, 0))
        tk.Button(bar, text="清空", font=FONT, width=8, relief="flat", bg=PANEL,
                  fg=C_ACCENT, command=self.clear, height=2).pack(side="left", padx=(8, 0))
        self.btn_emit = tk.Button(bar, text="关投影 · 看光斑", font=FONT, width=15,
                                  relief="flat", bg=PANEL, fg=C_TEXT, height=2,
                                  command=self.toggle_emitter)
        self.btn_emit.pack(side="left", padx=(8, 0))
        self.lbl_count = tk.Label(bar, text="已记录 0 株", font=FONT_MID, bg=BG, fg=C_TEXT)
        self.lbl_count.pack(side="right")

        table = tk.Frame(self.root, bg=BG, padx=16)
        table.pack(fill="x", pady=(0, 12))
        style = ttk.Style()
        style.configure("Treeview", font=FONT, rowheight=24)
        style.configure("Treeview.Heading", font=FONT)

        cols = ("idx", "laser", "cam", "diff", "spread", "valid", "sync", "time")
        heads = [
            ("idx", "序号", 55), ("laser", "激光 (mm)", 100), ("cam", "相机 (mm)", 100),
            ("diff", "差值 (mm)", 95), ("spread", "激光波动", 90),
            ("valid", "有效像素", 90), ("sync", "同步偏差 (ms)", 110), ("time", "时间 (s)", 90),
        ]
        self.tree = ttk.Treeview(table, columns=cols, show="headings", height=6)
        for key, title, width in heads:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="center")
        self.tree.pack(fill="x")

    # ---------- 设备发现 ----------

    def refresh_port_list(self):
        try:
            import port_probe
            ports = [p.device for p in port_probe.list_candidates()]
        except Exception:
            ports = []
        self.cmb_port["values"] = ports
        if ports and not self.cmb_port.get():
            self.cmb_port.set(self.laser.port or ports[0])

    def _self_heal(self):
        """端口已连接但长时间没有数据时，自动重新扫描，避免死连接。"""
        if self.demo or not self.use_laser or self.scanning:
            return
        now = time.time()
        if not self.laser.port:
            return
        if now - self.laser.connected_at < 3.0:
            return
        if now - self.laser.last_rx < 3.0:
            return
        if now - self.last_rescan < 6.0:
            return
        self.last_rescan = now
        self.auto_scan()

    def auto_scan(self):
        if self.scanning:
            return
        self.scanning = True
        self.lbl_laser_dev.config(text="正在扫描串口，请稍候...", fg=C_MUTED)
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self):
        try:
            self.laser.stop()
            import port_probe
            hits = port_probe.scan_lasers(window=0.6)
        except Exception as exc:
            self.scan_q.put(("error", str(exc)))
            return
        self.scan_q.put(("hits", hits))

    def _handle_scan(self, hits):
        self.scanning = False
        self.refresh_port_list()
        if not hits:
            self.lbl_laser_dev.config(
                text="未检测到激光设备（检查接线或手动选择端口）", fg=C_ACCENT)
            return
        h = hits[0]
        desc = h["desc"].replace("(", "").replace(")", "") if h["desc"] else "串口设备"
        self.lbl_laser_dev.config(
            text=f"{h['port']} · {desc} · VID_{h['vid']} PID_{h['pid']}", fg=C_TEXT)
        self.laser.start(h["port"], self.baud)
        self.cmb_port.set(h["port"])

    def connect_selected(self):
        port = self.cmb_port.get()
        if not port:
            return
        self.lbl_laser_dev.config(text=f"{port} · 正在连接...", fg=C_MUTED)
        self.laser.start(port, self.baud)

    def connect_port(self, port):
        self.laser.start(port, self.baud)
        self.lbl_laser_dev.config(text=f"{port} · 已连接", fg=C_TEXT)

    # ---------- 相机 ----------

    def _demo_laser(self):
        import random
        t0 = time.time()
        self.laser.port = "DEMO"
        self.laser.connected_at = t0
        while self.running:
            t = time.time() - t0
            base = 900 + 300 * (0.5 + 0.5 * ((t / 5) % 1))
            d = int(base + random.gauss(0, 4))
            now = time.time()
            self.laser.last_rx = now
            self.laser_q.put(("data", (now, d, 100 if d < 3000 else 40)))
            time.sleep(1 / 95)

    def _demo_cam(self):
        self.cam_ok = True
        self.cam_msg = "演示模式"
        self.cam_info = "DEMO · 合成深度图（非真实数据）"
        h, w = SRC_H, SRC_W
        yy, xx = np.mgrid[0:h, 0:w]
        while self.running:
            phase = time.time() % 8
            depth = (1300 + 500 * np.sin(xx / 70.0 + phase) + 250 * np.cos(yy / 45.0)).astype(np.uint16)
            color = np.zeros((h, w, 3), np.uint8)
            color[..., 1] = (xx * 255 // w).astype(np.uint8)
            color[..., 2] = (yy * 255 // h).astype(np.uint8)
            item = (time.time(), color, depth, None)
            try:
                self.cam_q.put_nowait(item)
            except queue.Full:
                try:
                    self.cam_q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self.cam_q.put_nowait(item)
                except queue.Full:
                    pass
            time.sleep(1 / 30)

    def _cam_loop(self):
        try:
            import pyrealsense2 as rs
            self._rs = rs
        except ImportError:
            self.cam_msg = "缺少 pyrealsense2"
            self.cam_info = "相机: 未安装 SDK"
            return
        # 必须先确认设备存在再调用 pipeline.start()：
        # 无设备时该调用会无限阻塞且不释放 GIL，会把整个进程锁死。
        try:
            ctx = rs.context()
            if not list(ctx.query_devices()):
                self.cam_msg = "未检测到相机"
                self.cam_info = "相机: 未连接（检查 USB）"
                return
        except Exception:
            pass

        try:
            pipeline = rs.pipeline()
            config = rs.config()
            config.enable_stream(rs.stream.color, SRC_W, SRC_H, rs.format.bgr8, 30)
            config.enable_stream(rs.stream.depth, SRC_W, SRC_H, rs.format.z16, 30)
            want_ir = True
            try:
                config.enable_stream(rs.stream.infrared, 1, SRC_W, SRC_H, rs.format.y8, 30)
            except Exception:
                want_ir = False
            try:
                profile = pipeline.start(config)
            except Exception:
                if not want_ir:
                    raise
                pipeline = rs.pipeline()
                config = rs.config()
                config.enable_stream(rs.stream.color, SRC_W, SRC_H, rs.format.bgr8, 30)
                config.enable_stream(rs.stream.depth, SRC_W, SRC_H, rs.format.z16, 30)
                profile = pipeline.start(config)
                want_ir = False
            self.has_ir = want_ir
            for sensor in profile.get_device().query_sensors():
                if sensor.supports(rs.option.global_time_enabled):
                    sensor.set_option(rs.option.global_time_enabled, 1)
            try:
                self.depth_sensor = profile.get_device().first_depth_sensor()
            except Exception:
                self.depth_sensor = None
            align = rs.align(rs.stream.color)
            dev = profile.get_device()
            try:
                name = dev.get_info(rs.camera_info.name)
                sn = dev.get_info(rs.camera_info.serial_number)
                fw = dev.get_info(rs.camera_info.firmware_version)
                self.cam_info = f"{name} · SN {sn} · FW {fw}"
            except Exception:
                self.cam_info = "RealSense 已连接"
            self.cam_ok = True
            self.cam_msg = "相机已连接"
        except Exception as exc:
            self.cam_msg = f"相机不可用: {exc}"
            self.cam_info = "相机: 未连接"
            return

        timeouts = 0
        while self.running:
            try:
                frames = pipeline.wait_for_frames(timeout_ms=2000)
                timeouts = 0
            except Exception:
                timeouts += 1
                if timeouts >= 5:
                    self.cam_ok = False
                    self.cam_msg = "相机无响应，已断开"
                    self.cam_info = "相机: 无响应"
                    return
                self.cam_msg = "等待帧超时"
                continue
            aligned = align.process(frames)
            dframe = aligned.get_depth_frame()
            cframe = aligned.get_color_frame()
            if not dframe or not cframe:
                continue
            ir = None
            if self.has_ir:
                try:
                    iframe = frames.get_infrared_frame(1)
                    if iframe:
                        ir = np.asanyarray(iframe.get_data()).copy()
                except Exception:
                    ir = None
            item = (frames.get_timestamp() / 1000.0,
                    np.asanyarray(cframe.get_data()).copy(),
                    np.asanyarray(dframe.get_data()).copy(),
                    ir)
            try:
                self.cam_q.put_nowait(item)
            except queue.Full:
                try:
                    self.cam_q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self.cam_q.put_nowait(item)
                except queue.Full:
                    pass
        try:
            pipeline.stop()
        except Exception:
            pass

    def reconnect_cam(self):
        if self.cam_ok:
            return
        self.cam_msg = "正在重连相机..."
        threading.Thread(target=self._cam_loop, daemon=True).start()

    def toggle_emitter(self):
        """关掉相机自带红外投影，让激光光斑成为红外图中唯一的亮点。"""
        if self.depth_sensor is None or self._rs is None:
            self.lbl_status.config(text="相机未连接，无法控制投影", fg=C_ACCENT)
            return
        try:
            rs = self._rs
            self.emitter_on = not self.emitter_on
            self.depth_sensor.set_option(rs.option.emitter_enabled,
                                         1 if self.emitter_on else 0)
            if self.emitter_on:
                self.btn_emit.config(text="关投影 · 看光斑", bg=PANEL, fg=C_TEXT)
                self.lbl_status.config(text="投影已开启，深度恢复正常", fg=C_MUTED)
            else:
                self.btn_emit.config(text="开投影 · 恢复深度", bg="#FCEBEB", fg=C_ACCENT)
                self.lbl_status.config(
                    text="投影已关闭，红外图里最亮的点就是激光光斑", fg=C_ACCENT)
        except Exception as exc:
            self.lbl_status.config(text=f"投影控制失败: {exc}", fg=C_ACCENT)

    # ---------- 交互 ----------

    def on_click(self, event):
        self.roi_cx = int(max(0, min(SRC_W - 1, event.x * SRC_W / IMG_W)))
        self.roi_cy = int(max(0, min(SRC_H - 1, event.y * SRC_H / IMG_H)))
        self._sync_roi_label()

    def on_wheel(self, event):
        self.roi_half = int(max(4, min(120, self.roi_half + (4 if event.delta > 0 else -4))))
        self._sync_roi_label()

    def load_roi(self):
        """加载上次标定的光斑位置，避免每次启动都要重新对准。"""
        try:
            with open(ROI_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.roi_cx = int(cfg.get("cx", SRC_W // 2))
            self.roi_cy = int(cfg.get("cy", SRC_H // 2))
            self.roi_half = int(cfg.get("half", 20))
            self.roi_loaded = True
        except Exception:
            self.roi_loaded = False

    def save_roi(self):
        try:
            with open(ROI_FILE, "w", encoding="utf-8") as f:
                json.dump({"cx": self.roi_cx, "cy": self.roi_cy,
                           "half": self.roi_half}, f, indent=2)
            self.roi_loaded = True
        except Exception:
            pass

    def _sync_roi_label(self):
        tag = "已标定" if self.roi_loaded else "未标定"
        self.lbl_roi.config(text=f"ROI ({self.roi_cx},{self.roi_cy}) "
                                 f"边长 {self.roi_half * 2 + 1}px · {tag}")
        self.save_roi()

    def _laser_recent(self):
        now = time.time()
        return [(t, d, c) for t, d, c in self.laser_data
                if now - t <= LASER_WINDOW and 0 < d < 8000]

    def _roi_depth(self):
        if self.latest_depth is None:
            return None, 0, 0
        d = self.latest_depth
        y0 = max(0, self.roi_cy - self.roi_half)
        y1 = min(SRC_H, self.roi_cy + self.roi_half + 1)
        x0 = max(0, self.roi_cx - self.roi_half)
        x1 = min(SRC_W, self.roi_cx + self.roi_half + 1)
        roi = d[y0:y1, x0:x1]
        valid = roi[roi > 0]
        if valid.size == 0:
            return None, 0, roi.size
        return float(np.median(valid)), int(valid.size), roi.size

    def mark(self):
        recent = self._laser_recent()
        laser_med = None
        spread = 0
        if recent:
            ds = sorted(d for _, d, _ in recent)
            laser_med = ds[len(ds) // 2]
            spread = ds[-1] - ds[0]
        cam_med, n_valid, _ = self._roi_depth()
        if laser_med is None and cam_med is None:
            return
        diff = (laser_med - cam_med) if (laser_med is not None and cam_med) else None
        sync = None
        if recent and self.latest_cam_t:
            sync = abs(recent[-1][0] - self.latest_cam_t) * 1000

        idx = len(self.marks) + 1
        rec = {
            "idx": idx,
            "laser": round(laser_med) if laser_med is not None else "",
            "cam": round(cam_med) if cam_med else "",
            "diff": round(diff) if diff is not None else "",
            "spread": round(spread),
            "valid": n_valid,
            "sync": round(sync) if sync is not None else "",
            "t": time.time() - self.t_start,
        }
        self.marks.append(rec)
        self.tree.insert("", "end", iid=str(idx), values=(
            idx, rec["laser"], rec["cam"], rec["diff"], rec["spread"],
            rec["valid"], rec["sync"], f"{rec['t']:.2f}"))
        self.tree.see(str(idx))
        self.lbl_count.config(text=f"已记录 {len(self.marks)} 株")
        self.btn_mark.config(bg="#9FE1CB")
        self.root.after(120, lambda: self.btn_mark.config(bg="#E1F5EE"))

    def undo(self):
        if not self.marks:
            return
        last = self.marks.pop()
        self.tree.delete(str(last["idx"]))
        self.lbl_count.config(text=f"已记录 {len(self.marks)} 株")

    def clear(self):
        self.marks.clear()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.lbl_count.config(text="已记录 0 株")
        self.laser_data.clear()
        self.t_start = time.time()

    def export(self):
        if not self.marks:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile="dual_sync.csv",
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["plant_no", "laser_mm", "camera_mm", "diff_mm",
                        "laser_spread_mm", "roi_valid_px", "sync_offset_ms", "t_rel_s"])
            for m in self.marks:
                w.writerow([m["idx"], m["laser"], m["cam"], m["diff"],
                            m["spread"], m["valid"], m["sync"], f"{m['t']:.3f}"])
        self.lbl_status.config(text=f"已导出 {len(self.marks)} 条", fg=C_OK)

    def _bring_to_front(self):
        """启动后把窗口顶到最前并夺取焦点，避免被已有窗口遮挡。"""
        try:
            self.root.deiconify()
            self.root.state("normal")
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(800, lambda: self.root.attributes("-topmost", False))
            self.root.focus_force()
        except Exception:
            pass

    def on_close(self):
        self.running = False
        try:
            self.laser.stop()
        except Exception:
            pass
        self.root.destroy()

    # ---------- 主循环 ----------

    def pump(self):
        got_img = False
        try:
            ts, cimg, dimg, ir = self.cam_q.get_nowait()
            self.latest_rgb = cimg
            self.latest_depth = dimg
            self.latest_ir = ir
            self.latest_cam_t = ts
            got_img = True
        except queue.Empty:
            pass

        for _ in range(200):
            try:
                kind, payload = self.scan_q.get_nowait()
            except queue.Empty:
                break
            if kind == "hits":
                self._handle_scan(payload)

        for _ in range(400):
            try:
                kind, payload = self.laser_q.get_nowait()
            except queue.Empty:
                break
            if kind == "error":
                self.lbl_laser_dev.config(text=payload, fg=C_ACCENT)
                continue
            self.laser_data.append(payload)

        self.lbl_cam_dev.config(text=self.cam_info,
                                fg=C_ACCENT if not self.cam_ok else C_TEXT)
        self._self_heal()
        self._update_numbers()
        if got_img:
            self._draw_images()
        self._draw_plot()
        self.pump_ts.append(time.time())
        ui_fps = 0.0
        if len(self.pump_ts) >= 2 and self.pump_ts[-1] > self.pump_ts[0]:
            ui_fps = (len(self.pump_ts) - 1) / (self.pump_ts[-1] - self.pump_ts[0])
        self.lbl_status.config(
            text=f"{self.laser.port or '未连接'} @ {self.baud} · {self.cam_msg} · UI {ui_fps:.1f}fps",
            fg=C_ACCENT if "失败" in self.cam_msg else C_MUTED)
        self.root.after(66, self.pump)

    def _update_numbers(self):
        recent = self._laser_recent()
        spread = None
        if recent:
            ds = sorted(d for _, d, _ in recent)
            self.lbl_laser.config(text=f"{ds[len(ds) // 2]:.0f}")
            spread = ds[-1] - ds[0]
        else:
            self.lbl_laser.config(text="--")

        cam_med, n_valid, total = self._roi_depth()
        self.lbl_cam.config(text=f"{cam_med:.0f}" if cam_med else "--")

        if recent and cam_med:
            cur = sorted(d for _, d, _ in recent)[len(recent) // 2]
            self.lbl_diff.config(text=f"{cur - cam_med:+.0f}")
        else:
            self.lbl_diff.config(text="--")

        sp = "--" if spread is None else f"{spread:.0f}mm"
        self.lbl_extra.config(text=f"波动 {sp} / {n_valid}/{total} 像素")

    def _draw_images(self):
        rgb = cv2.resize(self.latest_rgb, (IMG_W, IMG_H), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)

        d = np.clip(self.latest_depth.astype(np.float32), 0, 4000)
        d8 = (d / 4000 * 255).astype(np.uint8)
        dep = cv2.applyColorMap(d8, cv2.COLORMAP_JET)
        dep[self.latest_depth == 0] = (0, 0, 0)
        dep = cv2.resize(dep, (IMG_W, IMG_H), interpolation=cv2.INTER_NEAREST)
        dep = cv2.cvtColor(dep, cv2.COLOR_BGR2RGB)

        half = int(self.roi_half * IMG_W / SRC_W) + 2
        cx = int(self.roi_cx * IMG_W / SRC_W)
        cy = int(self.roi_cy * IMG_H / SRC_H)
        for img in (rgb, dep):
            cv2.rectangle(img, (cx - half, cy - half), (cx + half, cy + half), (212, 83, 126), 1)

        self.tk_rgb = ImageTk.PhotoImage(Image.fromarray(rgb))
        self.tk_dep = ImageTk.PhotoImage(Image.fromarray(dep))
        self.canvas_rgb.delete("all")
        self.canvas_rgb.create_image(0, 0, anchor="nw", image=self.tk_rgb)
        self.canvas_depth.delete("all")
        self.canvas_depth.create_image(0, 0, anchor="nw", image=self.tk_dep)

        self.canvas_ir.delete("all")
        if self.latest_ir is not None:
            irv = cv2.resize(self.latest_ir, (IMG_W, IMG_H), interpolation=cv2.INTER_AREA)
            lo = float(np.percentile(irv, 5))
            hi = float(np.percentile(irv, 99.5))
            if hi - lo > 8:
                irv = np.clip((irv.astype(np.float32) - lo) / (hi - lo) * 255,
                              0, 255).astype(np.uint8)
            ir_rgb = cv2.cvtColor(irv, cv2.COLOR_GRAY2RGB)
            self.tk_ir = ImageTk.PhotoImage(Image.fromarray(ir_rgb))
            self.canvas_ir.create_image(0, 0, anchor="nw", image=self.tk_ir)
        else:
            hint = "关闭投影后看光斑" if self.has_ir else "相机不支持红外流"
            self.canvas_ir.create_text(IMG_W // 2, IMG_H // 2, text=hint,
                                       fill="#888780", font=FONT_SM)

    def _draw_plot(self):
        c = self.canvas_plot
        c.delete("all")
        w = c.winfo_width()
        if w < 60:
            w = 300
        h = 100
        pad_l, pad_r, pad_t, pad_b = 40, 8, 8, 16

        if len(self.laser_data) < 2:
            c.create_text(w / 2, h / 2, text="等待激光数据...", fill=C_MUTED, font=FONT_SM)
            return

        now = time.time()
        t_lo = now - WIN_SEC
        window = [(t, d) for t, d, _ in self.laser_data if t >= t_lo and 0 < d < 8000]
        if len(window) < 2:
            return
        vals = [d for _, d in window]
        d_min, d_max = min(vals), max(vals)
        if d_max - d_min < 60:
            mid = (d_min + d_max) / 2
            d_min, d_max = mid - 30, mid + 30
        else:
            m = (d_max - d_min) * 0.2
            d_min, d_max = d_min - m, d_max + m

        pts = []
        for t, d in window:
            x = pad_l + (t - t_lo) / WIN_SEC * (w - pad_l - pad_r)
            y = pad_t + (1 - (d - d_min) / (d_max - d_min)) * (h - pad_t - pad_b)
            pts.extend([x, y])
        if len(pts) >= 4:
            c.create_line(*pts, fill="#85B7EB", width=1)
        c.create_text(pad_l - 4, pad_t + 4, text=f"{d_max:.0f}", anchor="e",
                      fill=C_MUTED, font=FONT_SM)
        c.create_text(pad_l - 4, h - pad_b, text=f"{d_min:.0f}", anchor="e",
                      fill=C_MUTED, font=FONT_SM)


def single_instance_guard():
    """用 Windows 命名互斥体做单实例检测，进程退出时自动释放，不依赖端口。"""
    try:
        import win32api
        import win32event
        import winerror
        mutex = win32event.CreateMutex(None, False, "Local\\TasselSyncGUI_v1")
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            return None
        return mutex
    except Exception:
        return True


def main():
    guard = single_instance_guard()
    if guard is None:
        try:
            tip = tk.Tk()
            tip.withdraw()
            win = tk.Toplevel(tip)
            win.title("提示")
            win.attributes("-topmost", True)
            win.geometry("360x150+760+440")
            tk.Label(win, text="界面已经在运行了\n请在任务栏或 Alt+Tab 里找一下窗口",
                     font=("Microsoft YaHei", 12), padx=24, pady=32).pack()
            tip.after(3000, tip.destroy)
            tip.mainloop()
        except Exception:
            pass
        sys.exit(0)

    missing = check_deps()
    hard = [m for m in missing if "(缺此项" not in m]
    if hard:
        print("缺少依赖: " + ", ".join(hard))
        print("请先执行: pip install " + " ".join(hard))
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("缺少依赖",
                                 "缺少以下库，无法启动：\n\n" + "\n".join(hard) +
                                 "\n\n请执行：\npip install " + " ".join(hard))
            root.destroy()
        except Exception:
            pass
        sys.exit(1)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    use_laser = "--nolaser" not in sys.argv
    demo = "--demo" in sys.argv
    port = args[0] if args else None
    baud = int(args[1]) if len(args) > 1 else 115200

    # 必须在启动后台线程之前完成重量级模块加载，
    # 否则主线程与后台线程会争抢全局 import 锁，导致界面卡在首帧。
    try:
        import numpy  # noqa: F401
        import cv2  # noqa: F401
        from PIL import Image, ImageTk  # noqa: F401
    except ImportError:
        pass

    root = tk.Tk()
    App(root, port, baud, use_laser, demo)
    root.mainloop()


if __name__ == "__main__":
    main()
