"""无显示器环境下的双传感器采集（树莓派 / 笔记本通用，不依赖 tkinter 与 GUI）。

按回车记录一株目标，数据逐行写入 CSV 并立即落盘，断电不丢。
ROI 从 roi_config.json 读取（在桌面版里标定一次即可）。

用法:
    python headless_capture.py --port auto --out data.csv
    python headless_capture.py --port COM6 --out data.csv
    python headless_capture.py --port /dev/ttyUSB0 --out data.csv
    python headless_capture.py --auto 3 --out data.csv      # 每 3 秒自动记一次
    python headless_capture.py --lowbw                        # 树莓派建议开启

树莓派注意事项:
    - 需要 USB 3.0 口（树莓派 4B 及以上），不要用 USB 2.0 扩展坞
    - pyrealsense2 在 ARM 上通常需要自行编译，见 README
    - 建议 --lowbw 降低分辨率与帧率，给 USB 带宽留余量
"""
import argparse
import csv
import json
import os
import sys
import threading
import time
from collections import deque

BASE = os.path.dirname(os.path.abspath(__file__))
ROI_FILE = os.path.join(BASE, "roi_config.json")
LASER_WINDOW = 0.15


def find_laser_port(baud=115200):
    """自动寻找输出距离帧的串口。"""
    from serial.tools import list_ports
    for p in list_ports.comports():
        hwid = (p.hwid or "").upper()
        if "BTHENUM" in hwid or p.device.upper() == "COM1":
            continue
        try:
            ser = __import__("serial").Serial(p.device, baud, timeout=0.1)
        except Exception:
            continue
        frames = 0
        t0 = time.time()
        while time.time() - t0 < 0.7:
            line = ser.readline().decode("ascii", "ignore").strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) == 2:
                try:
                    int(parts[0])
                    int(parts[1])
                    frames += 1
                except ValueError:
                    pass
            if frames >= 3:
                break
        ser.close()
        if frames >= 3:
            return p.device
    return None


class LaserThread(threading.Thread):
    def __init__(self, port, baud=115200):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.buf = deque(maxlen=400)
        self.running = True
        self.ok = False

    def run(self):
        try:
            import serial
            ser = serial.Serial(self.port, self.baud, timeout=0.2)
            ser.dtr = False
            ser.rts = False
            ser.reset_input_buffer()
            self.ok = True
        except Exception as exc:
            print(f"[警告] 激光串口打开失败: {exc}")
            return
        try:
            while self.running:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("ascii", "ignore").strip()
                parts = line.split(",")
                if len(parts) != 2:
                    continue
                try:
                    self.buf.append((time.time(), int(parts[0]), int(parts[1])))
                except ValueError:
                    continue
        finally:
            try:
                ser.close()
            except Exception:
                pass

    def recent(self, window=LASER_WINDOW):
        now = time.time()
        return [(t, d, c) for t, d, c in self.buf
                if now - t <= window and 0 < d < 20000]


def load_roi():
    try:
        with open(ROI_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return int(cfg["cx"]), int(cfg["cy"]), int(cfg["half"])
    except Exception:
        print(f"[提示] 未找到 {ROI_FILE}，ROI 使用画面中心。建议先在桌面版标定一次。")
        return 320, 240, 34


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="auto", help="激光串口，auto 为自动识别")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--out", default="capture.csv")
    ap.add_argument("--auto", type=float, default=0, help=">0 时按该秒数自动记录")
    ap.add_argument("--lowbw", action="store_true", help="低带宽模式，适合树莓派")
    args = ap.parse_args()

    try:
        import pyrealsense2 as rs
    except ImportError:
        print("缺少 pyrealsense2。树莓派上需要先编译 Librealsense，见 README。")
        sys.exit(1)

    port = args.port
    if port == "auto":
        print("正在自动识别激光串口...")
        port = find_laser_port(args.baud)
        if not port:
            print("未找到激光设备，退出。")
            sys.exit(1)
        print(f"识别到: {port}")

    laser = LaserThread(port, args.baud)
    laser.start()
    time.sleep(0.5)
    if not laser.ok:
        print("激光未就绪，退出。")
        sys.exit(1)

    w, h, fps = (424, 240, 15) if args.lowbw else (640, 480, 30)
    pipeline = rs.pipeline()
    cfg = rs.config()
    cfg.enable_stream(rs.stream.color, w, h, rs.format.bgr8, fps)
    cfg.enable_stream(rs.stream.depth, w, h, rs.format.z16, fps)
    try:
        profile = pipeline.start(cfg)
    except Exception as exc:
        print(f"相机启动失败: {exc}")
        sys.exit(1)
    align = rs.align(rs.stream.color)
    try:
        dev = profile.get_device()
        print(f"相机: {dev.get_info(rs.camera_info.name)} SN {dev.get_info(rs.camera_info.serial_number)}")
    except Exception:
        pass

    cx0, cy0, half0 = load_roi()
    scale_x = w / 640.0
    scale_y = h / 480.0
    cx, cy, half = int(cx0 * scale_x), int(cy0 * scale_y), max(4, int(half0 * scale_x))

    new_file = not os.path.exists(args.out)
    f = open(args.out, "a", newline="", encoding="utf-8-sig")
    writer = csv.writer(f)
    if new_file:
        writer.writerow(["plant_no", "laser_mm", "camera_mm", "diff_mm",
                         "laser_spread_mm", "roi_valid_px", "t_epoch", "roi"])
        f.flush()

    print(f"ROI=({cx},{cy}) 边长 {half * 2 + 1}px  |  输出 {args.out}")
    print("按回车记录一株，Ctrl+C 结束\n")

    count = 0
    latest_depth = None

    def grab_frames():
        nonlocal latest_depth
        while laser.running:
            try:
                frames = pipeline.wait_for_frames(2000)
            except Exception:
                continue
            aligned = align.process(frames)
            dframe = aligned.get_depth_frame()
            if dframe:
                import numpy as np
                latest_depth = np.asanyarray(dframe.get_data())

    threading.Thread(target=grab_frames, daemon=True).start()
    time.sleep(1.0)

    def record():
        nonlocal count, latest_depth
        import numpy as np
        recent = laser.recent()
        laser_med = None
        spread = 0
        if recent:
            ds = sorted(d for _, d, _ in recent)
            laser_med = ds[len(ds) // 2]
            spread = ds[-1] - ds[0]

        cam_med = None
        valid = 0
        if latest_depth is not None:
            y0, y1 = max(0, cy - half), min(latest_depth.shape[0], cy + half + 1)
            x0, x1 = max(0, cx - half), min(latest_depth.shape[1], cx + half + 1)
            roi = latest_depth[y0:y1, x0:x1]
            good = roi[roi > 0]
            valid = int(good.size)
            if valid:
                cam_med = float(np.median(good))

        if laser_med is None and cam_med is None:
            print("  两路都没有有效数据，跳过")
            return

        diff = (laser_med - cam_med) if (laser_med is not None and cam_med) else ""
        if isinstance(diff, float):
            diff = round(diff)
        count += 1
        writer.writerow([count,
                         round(laser_med) if laser_med is not None else "",
                         round(cam_med) if cam_med else "",
                         diff, round(spread), valid,
                         f"{time.time():.3f}", f"{cx},{cy},{half}"])
        f.flush()
        print(f"  #{count:<3} 激光 {laser_med if laser_med is not None else '-':>6} mm"
              f"  相机 {cam_med if cam_med else '-':>6} mm"
              f"  差值 {diff if diff != '' else '-':>5}"
              f"  波动 {spread:>4}  有效像素 {valid}")

    try:
        if args.auto > 0:
            print(f"自动模式：每 {args.auto}s 记录一次")
            while True:
                record()
                time.sleep(args.auto)
        else:
            while True:
                input()
                record()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        laser.running = False
        f.close()
        try:
            pipeline.stop()
        except Exception:
            pass
        print(f"\n结束，共记录 {count} 条 -> {args.out}")


if __name__ == "__main__":
    main()
