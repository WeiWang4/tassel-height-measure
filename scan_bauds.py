"""全波特率扫描：覆盖 4800-3000000，任一档收到任意字节即打印原始数据。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
BAUDS = [
    4800, 9600, 19200, 38400, 57600, 115200, 128000, 230400,
    256000, 460800, 500000, 921600, 1000000, 1500000, 2000000, 3000000,
]

hit = False
for baud in BAUDS:
    try:
        ser = serial.Serial(PORT, baud, timeout=0.05)
    except Exception as exc:
        print(f"{baud:>8}: 打开失败 {exc}")
        continue

    ser.reset_input_buffer()
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < 0.5:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.005)
    ser.close()

    if buf:
        hit = True
        txt = bytes(c if 0x20 <= c < 0x7F else 0x2E for c in buf[:40])
        print(f"{baud:>8}: {len(buf):>4} 字节  hex={bytes(buf[:20]).hex(' ')}")
        print(f"{'':>8}  可打印= {txt.decode('ascii', 'replace')}")
    else:
        print(f"{baud:>8}: 0 字节")

print()
if hit:
    print("结论: 有数据输出，按上面的波特率继续解析协议。")
else:
    print("结论: 全部波特率均无字节。模块没有向外发送数据。")
    print("排查顺序: 1) 模块 TX 是否接到串口板 RX  2) VDD 是否真的有 5V  3) 模块是否被配成 I2C/查询模式")
