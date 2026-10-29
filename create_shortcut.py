"""在桌面创建启动快捷方式（含自定义图标与全局热键）。"""
import os

from win32com.client import Dispatch

BASE = os.path.dirname(os.path.abspath(__file__))
PYW = r"D:\Program Files\Python311\pythonw.exe"
ICON = os.path.join(BASE, "icon.ico")

shell = Dispatch("WScript.Shell")
desktop = shell.SpecialFolders("Desktop")
lnk_path = os.path.join(desktop, "雄穗同步测定.lnk")

shortcut = shell.CreateShortCut(lnk_path)
shortcut.Targetpath = PYW
shortcut.Arguments = "dual_sync_gui.py"
shortcut.WorkingDirectory = BASE
shortcut.IconLocation = ICON
shortcut.Description = "激光 + 深度相机 雄穗穗位高同步测定"
shortcut.Hotkey = "CTRL+ALT+M"
shortcut.WindowStyle = 1
shortcut.save()

if os.path.exists(lnk_path):
    print("已创建:", lnk_path)
    print("目标:", PYW, "dual_sync_gui.py")
    print("工作目录:", BASE)
    print("图标:", ICON)
    print("热键: Ctrl+Alt+M")
else:
    print("创建失败")
