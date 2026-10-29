"""实时监听串口：边接线边看，通了立刻有反馈。可选参数 3 为原始数据落盘路径。

用法:
    python live_watch.py COM6 115200
    python live_watch.py COM6 115200 raw_log.bin
"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
LOGFILE = sys.argv[3] if len(sys.argv) > 3 else None

ser = serial.Serial(PORT, BAUD, timeout=0.05)
ser.dtr = False
ser.rts = False
ser.reset_input_buffer()

log = open(LOGFILE, "ab") if LOGFILE else None
total = 0
t0 = time.time()
last_report = t0

print(f"[{PORT} @ {BAUD}] 监听中，Ctrl+C 结束")
if LOGFILE:
    print(f"原始数据写入: {LOGFILE}")

try:
    while True:
        n = ser.in_waiting
        if n:
            data = ser.read(n)
            total += len(data)
            if log:
                log.write(data)
                log.flush()
            txt = bytes(c if 0x20 <= c < 0x7F else 0x2E for c in data[:48])
            print(f"  {time.time() - t0:7.2f}s  +{len(data):>3}B  累计 {total:>6}B  "
                  f"hex={bytes(data[:16]).hex(' ')}  |{txt.decode('ascii', 'replace')}|")
            last_report = time.time()
        else:
            time.sleep(0.002)
            now = time.time()
            if now - last_report > 2.0:
                print(f"  {now - t0:7.2f}s  -- 无数据 (累计 {total} 字节)")
                last_report = now
except KeyboardInterrupt:
    print(f"\n结束，共收到 {total} 字节")
finally:
    if log:
        log.close()
    ser.close()
