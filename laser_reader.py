"""Tiny ToF 读数解析器：帧格式 " <dist_mm>, <conf>\\n"

用法:
    python laser_reader.py COM6 115200 5          # 采 5 秒，看统计
    python laser_reader.py COM6 115200 30 out.csv # 采 30 秒并存 CSV
"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
DUR = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
CSVPATH = sys.argv[4] if len(sys.argv) > 4 else None

ser = serial.Serial(PORT, BAUD, timeout=0.2)
ser.dtr = False
ser.rts = False
ser.reset_input_buffer()

csv = open(CSVPATH, "w", encoding="utf-8") if CSVPATH else None
if csv:
    csv.write("t_s,dist_mm,conf\n")

t0 = time.time()
n = 0
bad = 0
vals = []
shown = 0

while time.time() - t0 < DUR:
    raw = ser.readline()
    if not raw:
        continue
    line = raw.decode("ascii", "ignore").strip()
    if not line:
        continue
    parts = line.split(",")
    if len(parts) != 2:
        bad += 1
        continue
    try:
        dist = int(parts[0].strip())
        conf = int(parts[1].strip())
    except ValueError:
        bad += 1
        continue

    t = time.time() - t0
    n += 1
    vals.append((dist, conf))
    if csv:
        csv.write(f"{t:.4f},{dist},{conf}\n")
    if shown < 12:
        print(f"  {t:6.3f}s  dist={dist:>5} mm  conf={conf:>3}")
        shown += 1

ser.close()
if csv:
    csv.close()

elapsed = time.time() - t0
print(f"\n采样 {elapsed:.2f}s，有效 {n} 帧，解析失败 {bad} 帧，帧率 {n / elapsed:.1f} Hz")
if vals:
    ds = [v[0] for v in vals]
    cs = [v[1] for v in vals]
    print(f"距离  min={min(ds)}  max={max(ds)}  均值={sum(ds) / len(ds):.1f} mm")
    print(f"置信度 min={min(cs)}  max={max(cs)}")
    if max(ds) >= 4000:
        print("注意: 出现 >=4000mm 的读数，通常是超量程后的无效值，需按置信度过滤")
if csv:
    print(f"已写入 {CSVPATH}")
