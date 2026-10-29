"""COM6 深度诊断：握手线状态 + 主动发起查询命令，判断模块是否在线。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"


def dump(tag, ser, seconds=1.2):
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < seconds:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.01)
    if buf:
        print(f"  [{tag}] 收到 {len(buf)} 字节: {bytes(buf[:24]).hex(' ')}")
        if any(0x20 <= c < 0x7F for c in buf):
            print(f"  [{tag}] 可打印: {bytes(c for c in buf if 0x20 <= c < 0x7F)[:60]}")
    else:
        print(f"  [{tag}] 无回应")
    return buf


for baud in (115200, 9600):
    print(f"\n=== {PORT} @ {baud} ===")
    try:
        ser = serial.Serial(PORT, baud, timeout=0.1)
    except Exception as exc:
        print(f"  打开失败: {exc}")
        continue

    print(f"  is_open={ser.is_open}  CTS={ser.cts} DSR={ser.dsr} CD={ser.cd} RI={ser.ri}")
    dump("静默", ser, 0.6)

    for name, payload in [
        ("TF版本查询", bytes([0x5A, 0x04, 0x01, 0x00, 0x5F])),
        ("TF保存设置", bytes([0x5A, 0x04, 0x11, 0x00, 0x6F])),
        ("ASCII AT", b"AT\r\n"),
    ]:
        ser.reset_input_buffer()
        ser.write(payload)
        ser.flush()
        dump(name, ser, 1.0)

    ser.close()

print("\n提示：若无任何回应，检查模块 VCC/GND 是否由串口板供电、TX/RX 是否交叉。")
