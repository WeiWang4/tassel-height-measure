"""量程与稳定性测试：实时显示读数，边移动模块边观察，结束时按距离分段统计。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
DUR = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0

ser = serial.Serial(PORT, BAUD, timeout=0.2)
ser.dtr = False
ser.rts = False
ser.reset_input_buffer()

print(f"[{PORT} @ {BAUD}] 量程测试，{DUR:.0f} 秒后自动结束，Ctrl+C 可提前停止")
print("操作: 把模块对着墙/走廊尽头，从近到远缓慢移动，观察读数是否跟随、置信度是否下降\n")

t0 = time.time()
vals = []
last_print = 0.0
last_val = None

try:
    while time.time() - t0 < DUR:
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

        t = time.time() - t0
        vals.append((dist, conf))
        last_val = dist

        now = time.time()
        if now - last_print > 0.15:
            recent = sorted(v[0] for v in vals[-10:])
            med = recent[len(recent) // 2]
            flag = "" if conf >= 30 and dist < 4000 else "  <- 可疑"
            print(f"  {t:6.2f}s  读数={dist:>5}mm  conf={conf:>3}  近10帧中位数={med:>5}mm{flag}")
            last_print = now
except KeyboardInterrupt:
    print("\n手动停止")

ser.close()
elapsed = time.time() - t0

print(f"\n===== 统计 =====")
print(f"时长 {elapsed:.1f}s，有效帧 {len(vals)}，帧率 {len(vals) / elapsed:.1f} Hz")
if not vals:
    sys.exit()

bins = {}
for d, c in vals:
    key = min(int(d // 500) * 500, 4000)
    bins.setdefault(key, []).append((d, c))

print(f"{'距离区间(mm)':<16}{'帧数':>6}{'占比':>8}{'均置信度':>10}{'读数抖动':>10}")
for key in sorted(bins):
    group = bins[key]
    ds = [g[0] for g in group]
    cs = [g[1] for g in group]
    span = max(ds) - min(ds)
    label = f"{key}-{key + 500}" if key < 4000 else ">=4000"
    print(f"{label:<16}{len(group):>6}{len(group) / len(vals) * 100:>7.1f}%"
          f"{sum(cs) / len(cs):>10.1f}{span:>9}mm")

far = max(d for d, _ in vals)
print(f"\n本次最远读数 {far} mm，对应置信度 "
      f"{[c for d, c in vals if d == far][0]}")
print("判读: 能稳定跟随且 conf>30 的最远距离，才是这个模块的可用量程。")
