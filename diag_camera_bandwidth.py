"""在受限带宽下寻找可用的流配置组合（USB 2.0 环境下排查掉帧用）。

注意: infrared 流多一个 stream index 参数，其余流没有，这里统一用 6 元组描述。
"""
import time

import pyrealsense2 as rs

CONFIGS = [
    ("640x480@30 三路", [(rs.stream.color, 0, 640, 480, rs.format.bgr8, 30),
                        (rs.stream.depth, 0, 640, 480, rs.format.z16, 30),
                        (rs.stream.infrared, 1, 640, 480, rs.format.y8, 30)]),
    ("640x480@30 两路", [(rs.stream.color, 0, 640, 480, rs.format.bgr8, 30),
                        (rs.stream.depth, 0, 640, 480, rs.format.z16, 30)]),
    ("640x480@15 两路", [(rs.stream.color, 0, 640, 480, rs.format.bgr8, 15),
                        (rs.stream.depth, 0, 640, 480, rs.format.z16, 15)]),
    ("640x480@15 + IR@15", [(rs.stream.color, 0, 640, 480, rs.format.bgr8, 15),
                           (rs.stream.depth, 0, 640, 480, rs.format.z16, 15),
                           (rs.stream.infrared, 1, 640, 480, rs.format.y8, 15)]),
    ("424x240@30 两路", [(rs.stream.color, 0, 424, 240, rs.format.bgr8, 30),
                        (rs.stream.depth, 0, 424, 240, rs.format.z16, 30)]),
    ("424x240@30 + IR", [(rs.stream.color, 0, 424, 240, rs.format.bgr8, 30),
                        (rs.stream.depth, 0, 424, 240, rs.format.z16, 30),
                        (rs.stream.infrared, 1, 424, 240, rs.format.y8, 30)]),
    ("480x270@30 两路", [(rs.stream.color, 0, 480, 270, rs.format.bgr8, 30),
                        (rs.stream.depth, 0, 480, 270, rs.format.z16, 30)]),
]


def device_count():
    try:
        return len(list(rs.context().query_devices()))
    except Exception:
        return 0


count = device_count()
print(f"检测到 {count} 台 RealSense 设备")
if count == 0:
    print("未连接相机，跳过测试。")
    raise SystemExit(0)

for d in rs.context().query_devices():
    print("  ", d.get_info(rs.camera_info.name),
          "| USB", d.get_info(rs.camera_info.usb_type_descriptor))

for label, streams in CONFIGS:
    pl = None
    ok = False
    detail = ""
    try:
        pl = rs.pipeline()
        cfg = rs.config()
        for stream, idx, w, h, fmt, fps in streams:
            if stream == rs.stream.infrared:
                cfg.enable_stream(stream, idx, w, h, fmt, fps)
            else:
                cfg.enable_stream(stream, w, h, fmt, fps)
        pl.start(cfg)
        lat = []
        for _ in range(6):
            t0 = time.time()
            pl.wait_for_frames(3000)
            lat.append((time.time() - t0) * 1000)
        ok = True
        detail = f"平均取帧 {sum(lat) / len(lat):.0f} ms"
    except Exception as exc:
        detail = repr(exc)[:90]
    finally:
        if pl is not None:
            try:
                pl.stop()
            except Exception:
                pass
        time.sleep(0.8)
    print(f"[{'OK  ' if ok else 'FAIL'}] {label:22s} {detail}")
