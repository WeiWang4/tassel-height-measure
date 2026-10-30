"""RealSense 流握手诊断：确认能否启动彩色 / 深度 / 红外三路流。"""
import pyrealsense2 as rs

ctx = rs.context()
devs = list(ctx.query_devices())
print(f"设备数: {len(devs)}\n")

for d in devs:
    print("型号:", d.get_info(rs.camera_info.name))
    print("SN  :", d.get_info(rs.camera_info.serial_number))
    try:
        print("固件:", d.get_info(rs.camera_info.firmware_version))
    except Exception:
        pass
    try:
        print("USB :", d.get_info(rs.camera_info.usb_type_descriptor))
    except Exception:
        print("USB : 读取失败")


def attempt(with_ir):
    pl = rs.pipeline()
    cfg = rs.config()
    cfg.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)
    cfg.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
    if with_ir:
        cfg.enable_stream(rs.stream.infrared, 1, 640, 480, rs.format.y8, 30)
    return pl, pl.start(cfg)


for label, with_ir in (("三路流 color+depth+IR", True), ("两路流 color+depth", False)):
    print(f"\n--- {label} ---")
    pl = None
    try:
        pl, _ = attempt(with_ir)
        print("启动成功")
        for i in range(5):
            fs = pl.wait_for_frames(2000)
            c = fs.get_color_frame()
            d = fs.get_depth_frame()
            ir = None
            if with_ir:
                try:
                    ir = fs.get_infrared_frame(1)
                except Exception:
                    ir = None
            print(f"  第{i + 1}帧  color={c is not None}  depth={d is not None}  ir={ir is not None}")
    except Exception as exc:
        print("启动失败:", repr(exc))
    finally:
        if pl is not None:
            try:
                pl.stop()
            except Exception:
                pass
