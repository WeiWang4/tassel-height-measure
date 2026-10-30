"""枚举系统中所有 Tk 窗口（含不可见的），确认窗口是否真的被创建。"""
import win32api
import win32gui

found = []
total = [0]


def callback(hwnd, _):
    total[0] += 1
    try:
        cls = win32gui.GetClassName(hwnd)
        if cls.startswith("Tk"):
            found.append({
                "hwnd": hwnd,
                "class": cls,
                "title": win32gui.GetWindowText(hwnd),
                "visible": bool(win32gui.IsWindowVisible(hwnd)),
                "iconic": bool(win32gui.IsIconic(hwnd)),
                "rect": win32gui.GetWindowRect(hwnd),
            })
    except Exception:
        pass


win32gui.EnumWindows(callback, None)

try:
    sw = win32api.GetSystemMetrics(0)
    sh = win32api.GetSystemMetrics(1)
except Exception:
    sw = sh = 0

print(f"屏幕: {sw} x {sh}   枚举到顶层窗口总数: {total[0]}")
print(f"其中 Tk 窗口: {len(found)}")
for w in found:
    left, top, right, bottom = w["rect"]
    print(f"  hwnd={w['hwnd']} class={w['class']} visible={w['visible']} "
          f"minimized={w['iconic']} pos=({left},{top}) size={right - left}x{bottom - top} "
          f"title=[{w['title']}]")
