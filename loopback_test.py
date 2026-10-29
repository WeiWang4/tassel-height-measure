"""CH340 回环自检：把串口板的 TX 和 RX 用杜邦线短接后运行，能收到自己发的数据即说明板子正常。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
BAUD = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

ser = serial.Serial(PORT, BAUD, timeout=0.2)
ser.reset_input_buffer()
time.sleep(0.1)

payload = bytes([0x5A, 0xA5, 0x11, 0x22, 0x33])
ser.write(payload)
ser.flush()

time.sleep(0.3)
echo = ser.read(64)
ser.close()

print(f"发送: {payload.hex(' ')}")
print(f"收到: {echo.hex(' ') if echo else '(空)'}")

if echo == payload:
    print("结果: 回环正常，串口板与驱动没有问题 -> 问题在测距模块侧（供电/接线/模式）")
elif echo:
    print(f"结果: 收到但不一致（{len(echo)} 字节），可能存在电平或波特率偏差")
else:
    print("结果: 无回环 -> 短接线没接好，或串口板 TX/RX 损坏")
