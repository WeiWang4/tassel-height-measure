"""DTR/RTS 组合扫描：部分模块的 MCU 复位脚被 DTR 拉住，会一直不出数据。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

COMBOS = [(False, False), (True, False), (False, True), (True, True)]

for dtr, rts in COMBOS:
    ser = serial.Serial()
    ser.port = PORT
    ser.baudrate = BAUD
    ser.timeout = 0.05
    ser.rtscts = False
    ser.dsrdtr = False
    try:
        ser.open()
    except Exception as exc:
        print(f"DTR={dtr} RTS={rts}: 打开失败 {exc}")
        continue

    ser.dtr = dtr
    ser.rts = rts
    time.sleep(0.3)
    ser.reset_input_buffer()

    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < 1.5:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.005)

    print(f"DTR={str(dtr):<5} RTS={str(rts):<5} -> {len(buf):>4} 字节")
    if buf:
        print(f"          hex={bytes(buf[:24]).hex(' ')}")
        txt = bytes(c if 0x20 <= c < 0x7F else 0x2E for c in buf[:48])
        print(f"          文本={txt.decode('ascii', 'replace')}")
    ser.close()

print("\n如果四种组合都是 0 字节，可以判定模块 TX 没有信号送进来。")
