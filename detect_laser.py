"""探测 COM6 上的激光测距模块：识别波特率与数据帧格式。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
BAUDS = [115200, 921600, 230400, 57600, 9600, 128000]


def probe(baud):
    try:
        ser = serial.Serial(PORT, baud, timeout=0.05)
    except Exception as exc:
        return f"打开失败: {exc}"
    ser.reset_input_buffer()
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < 0.9:
        waiting = ser.in_waiting
        if waiting:
            buf += ser.read(waiting)
        else:
            time.sleep(0.01)
    ser.close()

    if not buf:
        return "无数据"

    frames = 0
    samples = []
    i = 0
    while i < len(buf) - 8:
        if buf[i] == 0x59 and buf[i + 1] == 0x59 and (sum(buf[i:i + 8]) & 0xFF) == buf[i + 8]:
            dist = buf[i + 2] | (buf[i + 3] << 8)
            strength = buf[i + 4] | (buf[i + 5] << 8)
            frames += 1
            if len(samples) < 6:
                samples.append((dist, strength))
            i += 9
            continue
        i += 1

    printable = bytes(c for c in buf if 0x20 <= c < 0x7F or c in (0x0D, 0x0A))
    ascii_lines = [l for l in printable.split(b"\r\n") if l.strip()][:3]

    out = f"{len(buf):>5} 字节 | 0x59 帧 {frames:>3} | 样本(cm,strength) {samples}"
    if ascii_lines:
        out += f" | ASCII {ascii_lines}"
    return out


print(f"端口 {PORT}")
for b in BAUDS:
    print(f"{b:>7}: {probe(b)}")
