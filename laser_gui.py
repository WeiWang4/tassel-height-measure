"""激光测距 · 逐株手动打点界面（零依赖，tkinter）。

操作:
    空格 / 点击大按钮  -> 对当前对准的目标记录一个测量值
    Ctrl+Z             -> 撤销上一条
    导出 CSV           -> 保存全部打点记录

记录逻辑: 按下瞬间取最近 0.15 秒（约 14 帧 @94Hz）的距离中位数作为该株测量值，
同时记录波动范围与平均置信度，避免单帧噪声直接进入数据。

用法:
    python laser_gui.py                 # COM6 @ 115200
    python laser_gui.py COM6 115200
    python laser_gui.py --demo          # 无硬件预览
"""
import csv
import queue
import random
import sys
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import filedialog, ttk

WIN_SEC = 10.0
MARK_WINDOW = 0.15
MAX_POINTS = 4000

BG = "#FFFFFF"
PANEL = "#F5F5F3"
LINE = "#D0CFC9"
C_RAW = "#85B7EB"
C_MARK = "#D4537E"
C_TEXT = "#2C2C2A"
C_MUTED = "#888780"
C_GRID = "#E8E7E2"
C_ACCENT = "#A32D2D"
C_OK = "#0F6E56"

FONT = ("Microsoft YaHei", 10)
FONT_BIG = ("Microsoft YaHei", 42)
FONT_MID = ("Microsoft YaHei", 13)
FONT_SM = ("Microsoft YaHei", 9)
FONT_BTN = ("Microsoft YaHei", 12)


class App:
    def __init__(self, root, port, baud, demo=False):
        self.root = root
        self.port = port
        self.baud = baud
        self.demo = demo
        self.q = queue.Queue()
        self.running = True

        self.data = deque(maxlen=MAX_POINTS)
        self.marks = []
        self.t_start = time.time()
        self.status = "正在连接..."

        root.title("激光测距 · 逐株手动打点")
        root.geometry("1080x780")
        root.configure(bg=BG)
        root.minsize(880, 640)

        self._build()
        self._start_source()

        root.bind("<space>", lambda e: self.mark())
        root.bind("<Control-z>", lambda e: self.undo())
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.pump()

    def _build(self):
        top = tk.Frame(self.root, bg=BG, padx=16, pady=10)
        top.pack(fill="x")
        tk.Label(top, text="激光测距 · 逐株手动打点", font=("Microsoft YaHei", 13),
                 bg=BG, fg=C_TEXT).pack(side="left")
        self.lbl_status = tk.Label(top, text="正在连接...", font=FONT_SM, bg=BG, fg=C_MUTED)
        self.lbl_status.pack(side="right")

        mid = tk.Frame(self.root, bg=BG, padx=16)
        mid.pack(fill="both", expand=True)

        left = tk.Frame(mid, bg=PANEL, padx=16, pady=14, width=230)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        tk.Label(left, text="实时距离", font=FONT_SM, bg=PANEL, fg=C_MUTED).pack(anchor="w")
        self.lbl_dist = tk.Label(left, text="--", font=FONT_BIG, bg=PANEL, fg=C_MUTED)
        self.lbl_dist.pack(anchor="w")
        tk.Label(left, text="mm", font=FONT_SM, bg=PANEL, fg=C_MUTED).pack(anchor="w")

        tk.Frame(left, bg=LINE, height=1).pack(fill="x", pady=12)

        tk.Label(left, text="待记录值（近 0.15s 中位数）", font=FONT_SM, bg=PANEL, fg=C_MUTED).pack(anchor="w")
        self.lbl_pending = tk.Label(left, text="--", font=FONT_MID, bg=PANEL, fg=C_ACCENT)
        self.lbl_pending.pack(anchor="w", pady=(2, 0))

        tk.Label(left, text="波动范围", font=FONT_SM, bg=PANEL, fg=C_MUTED).pack(anchor="w", pady=(10, 0))
        self.lbl_spread = tk.Label(left, text="-- mm", font=FONT_MID, bg=PANEL, fg=C_TEXT)
        self.lbl_spread.pack(anchor="w", pady=(2, 0))

        tk.Label(left, text="置信度 / 帧率", font=FONT_SM, bg=PANEL, fg=C_MUTED).pack(anchor="w", pady=(10, 0))
        self.lbl_conf = tk.Label(left, text="-- / --", font=FONT_MID, bg=PANEL, fg=C_TEXT)
        self.lbl_conf.pack(anchor="w", pady=(2, 0))

        right = tk.Frame(mid, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.canvas = tk.Canvas(right, bg=BG, highlightthickness=1,
                                highlightbackground=LINE)
        self.canvas.pack(fill="both", expand=True)

        bar = tk.Frame(self.root, bg=BG, padx=16, pady=10)
        bar.pack(fill="x")

        self.btn_mark = tk.Button(bar, text="打点记录  (空格)", font=FONT_BTN, width=20,
                                  relief="flat", bg="#E1F5EE", fg=C_OK,
                                  activebackground="#9FE1CB", command=self.mark, height=2)
        self.btn_mark.pack(side="left")

        tk.Button(bar, text="撤销  (Ctrl+Z)", font=FONT, width=14, relief="flat",
                  bg=PANEL, fg=C_TEXT, command=self.undo, height=2).pack(side="left", padx=(8, 0))
        tk.Button(bar, text="导出 CSV", font=FONT, width=12, relief="flat",
                  bg=PANEL, fg=C_TEXT, command=self.export, height=2).pack(side="left", padx=(8, 0))
        tk.Button(bar, text="全部清空", font=FONT, width=10, relief="flat",
                  bg=PANEL, fg=C_ACCENT, command=self.clear, height=2).pack(side="left", padx=(8, 0))

        self.lbl_count = tk.Label(bar, text="已记录 0 株", font=FONT_MID, bg=BG, fg=C_TEXT)
        self.lbl_count.pack(side="right", padx=(0, 4))

        table = tk.Frame(self.root, bg=BG, padx=16)
        table.pack(fill="x", pady=(0, 12))

        style = ttk.Style()
        style.configure("Treeview", font=FONT, rowheight=24)
        style.configure("Treeview.Heading", font=FONT)

        cols = ("idx", "dist", "conf", "spread", "time")
        self.tree = ttk.Treeview(table, columns=cols, show="headings", height=6)
        heads = {"idx": ("序号", 60), "dist": ("距离 (mm)", 120), "conf": ("置信度", 90),
                 "spread": ("波动 (mm)", 110), "time": ("相对时间 (s)", 120)}
        for key, (title, width) in heads.items():
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="center")
        self.tree.pack(fill="x")

    def _start_source(self):
        if self.demo:
            self.status = "演示模式（模拟数据）"
            threading.Thread(target=self._demo_loop, daemon=True).start()
        else:
            threading.Thread(target=self._serial_loop, daemon=True).start()

    def _serial_loop(self):
        try:
            import serial
            ser = serial.Serial(self.port, self.baud, timeout=0.2)
            ser.dtr = False
            ser.rts = False
            ser.reset_input_buffer()
        except Exception as exc:
            self.q.put(("error", f"打开 {self.port} 失败: {exc}"))
            return

        self.status = f"{self.port} @ {self.baud} 已连接"
        while self.running:
            raw = ser.readline()
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
            self.q.put(("data", (dist, conf)))
        try:
            ser.close()
        except Exception:
            pass

    def _demo_loop(self):
        t0 = time.time()
        while self.running:
            t = time.time() - t0
            base = 880 + 300 * (0.5 + 0.5 * ((t / 6) % 1))
            dist = int(base + random.gauss(0, 4))
            conf = 100 if dist < 3200 else max(0, 100 - (dist - 3200) // 40)
            self.q.put(("data", (dist, conf)))
            time.sleep(1 / 95)

    def _recent(self, window=MARK_WINDOW):
        now = time.time()
        return [(t, d, c) for t, d, c in self.data if now - t <= window and 0 < d < 8000]

    def mark(self):
        recent = self._recent()
        if not recent:
            return
        ds = sorted(d for _, d, _ in recent)
        med = ds[len(ds) // 2]
        conf = sum(c for _, _, c in recent) / len(recent)
        spread = ds[-1] - ds[0]
        idx = len(self.marks) + 1
        rec = {"idx": idx, "dist": round(med), "conf": round(conf),
               "spread": spread, "t": time.time() - self.t_start}
        self.marks.append(rec)
        self.tree.insert("", "end", iid=str(idx), values=(
            idx, f"{med:.0f}", f"{conf:.0f}", f"{spread:.0f}", f"{rec['t']:.2f}"))
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
        self.data.clear()
        self.t_start = time.time()

    def export(self):
        if not self.marks:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile="tassel_height.csv",
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["plant_no", "dist_mm", "conf", "spread_mm", "t_rel_s"])
            for m in self.marks:
                w.writerow([m["idx"], m["dist"], m["conf"], m["spread"], f"{m['t']:.3f}"])
        self.status = f"已导出 {len(self.marks)} 条 -> {path}"
        self.lbl_status.config(text=self.status, fg=C_OK)

    def on_close(self):
        self.running = False
        self.root.destroy()

    def pump(self):
        now = time.time()
        while not self.q.empty():
            kind, payload = self.q.get()
            if kind == "error":
                self.status = payload
                self.lbl_status.config(text=payload, fg=C_ACCENT)
                continue
            d, c = payload
            self.data.append((now, d, c))

        self.lbl_status.config(text=self.status,
                               fg=C_ACCENT if "失败" in self.status else C_MUTED)
        self.draw(now)
        self.root.after(50, self.pump)

    def draw(self, now):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width() or 600
        h = c.winfo_height() or 320
        pad_l, pad_r, pad_t, pad_b = 58, 16, 18, 26

        recent = self._recent()
        if recent:
            ds = sorted(d for _, d, _ in recent)
            med = ds[len(ds) // 2]
            self.lbl_dist.config(text=f"{self.data[-1][1]}", fg=C_ACCENT)
            self.lbl_pending.config(text=f"{med:.0f} mm")
            self.lbl_spread.config(text=f"{ds[-1] - ds[0]:.0f} mm")
            conf = sum(cf for _, _, cf in recent) / len(recent)
            elapsed = max(now - self.t_start, 0.1)
            self.lbl_conf.config(text=f"{conf:.0f} / {len(self.data) / min(elapsed, 10):.1f} Hz")
        else:
            self.lbl_dist.config(text="--", fg=C_MUTED)
            self.lbl_pending.config(text="--")
            self.lbl_spread.config(text="-- mm")
            self.lbl_conf.config(text="-- / --")

        if len(self.data) < 2:
            c.create_text(w / 2, h / 2, text="等待数据...", fill=C_MUTED, font=FONT_MID)
            return

        t_hi = now
        t_lo = t_hi - WIN_SEC
        window = [p for p in self.data if p[0] >= t_lo]
        if len(window) < 2:
            window = list(self.data)[-2:]

        vals = [p[1] for p in window if 0 < p[1] < 8000]
        if not vals:
            return
        d_min, d_max = min(vals), max(vals)
        if d_max - d_min < 120:
            mid = (d_max + d_min) / 2
            d_min, d_max = mid - 60, mid + 60
        else:
            m = (d_max - d_min) * 0.15
            d_min, d_max = d_min - m, d_max + m

        def X(t):
            return pad_l + (t - t_lo) / WIN_SEC * (w - pad_l - pad_r)

        def Y(d):
            return pad_t + (1 - (d - d_min) / (d_max - d_min)) * (h - pad_t - pad_b)

        for i in range(5):
            val = d_min + (d_max - d_min) * i / 4
            y = Y(val)
            c.create_line(pad_l, y, w - pad_r, y, fill=C_GRID, width=0.5)
            c.create_text(pad_l - 8, y, text=f"{val:.0f}", anchor="e", fill=C_MUTED, font=FONT_SM)

        for i in range(6):
            x = X(t_lo + WIN_SEC * i / 5)
            c.create_line(x, pad_t, x, h - pad_b, fill=C_GRID, width=0.5)
            c.create_text(x, h - pad_b + 12, text=f"-{WIN_SEC - WIN_SEC * i / 5:.0f}s",
                          fill=C_MUTED, font=FONT_SM)

        pts = []
        for t, d, _ in window:
            if 0 < d < 8000:
                pts.extend([X(t), Y(d)])
        if len(pts) >= 4:
            c.create_line(*pts, fill=C_RAW, width=1)

        for m in self.marks[-15:]:
            mt = self.t_start + m["t"]
            if mt >= t_lo:
                x = X(mt)
                c.create_line(x, pad_t, x, h - pad_b, fill=C_MARK, width=1, dash=(3, 3))
                y = Y(m["dist"])
                c.create_oval(x - 3, y - 3, x + 3, y + 3, fill=C_MARK, outline="")
                c.create_text(x, pad_t - 6, text=str(m["idx"]), fill=C_MARK, font=FONT_SM)

        if self.data:
            d = self.data[-1][1]
            if 0 < d < 8000:
                y = Y(d)
                c.create_line(pad_l, y, w - pad_r, y, fill=C_ACCENT, width=0.7, dash=(2, 3))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    demo = "--demo" in sys.argv
    port = args[0] if args else "COM6"
    baud = int(args[1]) if len(args) > 1 else 115200

    root = tk.Tk()
    App(root, port, baud, demo)
    root.mainloop()


if __name__ == "__main__":
    main()
