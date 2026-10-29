"""串口自动识别：从所有 COM 口里找出真正输出激光距离数据的那一个。

不依赖固定端口号和固定 VID，换一台电脑、换一个 USB 口都能自己找到。
"""
import time

import serial
from serial.tools import list_ports

LASER_BAUD = 115200


def _parse_frame(raw):
    """激光模块协议: ' <dist_mm>, <conf>\\n'"""
    line = raw.decode("ascii", "ignore").strip()
    if not line:
        return None
    parts = line.split(",")
    if len(parts) != 2:
        return None
    try:
        dist = int(parts[0].strip())
        conf = int(parts[1].strip())
    except ValueError:
        return None
    if 0 <= dist <= 20000 and 0 <= conf <= 1000:
        return dist, conf
    return None


def probe_port(port, baud=LASER_BAUD, window=0.6, need_frames=3):
    """打开端口读一小段时间，返回 (是否命中, 帧数, 最新读数)。"""
    try:
        ser = serial.Serial(port, baud, timeout=0.05)
    except Exception:
        return False, 0, None
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass
    try:
        ser.reset_input_buffer()
    except Exception:
        pass

    frames = 0
    last = None
    t0 = time.time()
    while time.time() - t0 < window:
        try:
            raw = ser.readline()
        except Exception:
            break
        if not raw:
            continue
        parsed = _parse_frame(raw)
        if parsed:
            frames += 1
            last = parsed
            if frames >= need_frames:
                break
    try:
        ser.close()
    except Exception:
        pass
    return frames >= need_frames, frames, last


def list_candidates():
    """列出可能承载激光模块的串口，过滤掉蓝牙与主板串口。"""
    out = []
    for p in list_ports.comports():
        hwid = p.hwid or ""
        if "BTHENUM" in hwid.upper():
            continue
        if p.device.upper() == "COM1":
            continue
        out.append(p)
    return out


def scan_lasers(baud=LASER_BAUD, window=0.6):
    """扫描全部候选端口，返回命中的设备信息列表。"""
    found = []
    for p in list_candidates():
        ok, frames, last = probe_port(p.device, baud, window)
        if ok:
            vid = ""
            pid = ""
            hwid_upper = (p.hwid or "").upper()
            if "VID_" in hwid_upper:
                try:
                    vid = hwid_upper.split("VID_")[1][:4]
                except IndexError:
                    pass
            if "PID_" in hwid_upper:
                try:
                    pid = hwid_upper.split("PID_")[1][:4]
                except IndexError:
                    pass
            found.append({
                "port": p.device,
                "desc": p.description or "",
                "hwid": p.hwid or "",
                "vid": vid,
                "pid": pid,
                "frames": frames,
                "last": last,
            })
    return found


if __name__ == "__main__":
    print("正在扫描串口...")
    ports = list_candidates()
    print(f"候选端口 {len(ports)} 个: {[p.device for p in ports]}")
    hits = scan_lasers()
    if not hits:
        print("未找到激光测距设备")
    for h in hits:
        dist = h["last"][0] if h["last"] else "-"
        print(f"命中 {h['port']} | {h['desc']} | VID_{h['vid']} PID_{h['pid']} "
              f"| 0.6s 内 {h['frames']} 帧 | 当前 {dist} mm")
