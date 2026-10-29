# tassel-height-measure

玉米雄穗形态参数同步测定工具 / Synchronous measurement of maize tassel height

基于**单点 ToF 激光测距模块**与 **Intel RealSense 深度相机**的双传感器同步采集界面，用于逐株手动测定雄穗穗位高，并输出两套独立测距原理的一致性对照数据。

## 硬件配置

| 部件 | 规格 |
|---|---|
| 激光测距 | 单点 ToF 模块，ASCII 协议 `" <dist_mm>, <conf>\n"`，115200 bps，实测 94.7 Hz |
| 深度相机 | Intel RealSense D4xx，RGB 640×480 + Depth 640×480 @30fps，深度对齐到彩色 |
| 转接 | USB-TTL 串口板（CH340） |

## 功能

- **串口自动识别**：启动时扫描全部 COM 口，逐口试读，命中数据帧即认定为激光模块。不依赖固定端口号或 VID，换电脑、换 USB 口都无需改代码。
- **双路实时显示**：彩色图与深度伪彩图并排，鼠标点击设定 ROI 位置、滚轮调整大小，用于对准激光光斑。
- **逐株手动打点**：空格键记录当前对准的一株，激光值取最近 0.15 s 中位数以抑制单帧噪声。
- **一致性对照**：同一次打点同时记录激光读数、相机深度、两者差值、激光波动、ROI 有效像素比例、同步偏差。
- **CSV 导出**：一键导出全部记录。
- **自动恢复**：激光端口掉线后自动重扫重连；相机连续取帧超时判定断开，可手动重连。

## 安装

```bash
python -m pip install pyserial opencv-python pillow numpy pyrealsense2
```

Windows 下可直接双击 `install_deps.bat`（含依赖校验）。

要求 Python 3.8–3.12。`pyrealsense2` 对 Python 3.13+ 的官方 wheel 支持不完整。

## 使用

```bash
python dual_sync_gui.py                 # 自动识别全部设备
python dual_sync_gui.py COM6 115200     # 指定端口
python dual_sync_gui.py --nolaser       # 只接深度相机
python dual_sync_gui.py --demo          # 无硬件，合成数据预览界面
```

Windows 下双击 `start.bat`。

### 操作

| 操作 | 作用 |
|---|---|
| 空格 | 打点记录当前一株 |
| Ctrl+Z | 撤销上一条 |
| 鼠标点击图像 | 把测量 ROI 移到点击位置（对准激光光斑） |
| 鼠标滚轮 | 调整 ROI 边长 |
| 重新扫描 | 重新识别激光端口 |
| 重连相机 | 相机掉线后尝试恢复 |

## 输出数据格式

```
plant_no, laser_mm, camera_mm, diff_mm, laser_spread_mm, roi_valid_px, sync_offset_ms, t_rel_s
```

| 字段 | 含义 |
|---|---|
| `laser_mm` | 激光斜距，为打点前 0.15 s 内有效读数的中位数 |
| `camera_mm` | ROI 内有效深度像素的中位数 |
| `diff_mm` | 两者之差，用于一致性验证；偏离过大说明至少一路打在了非目标表面 |
| `laser_spread_mm` | 0.15 s 内激光读数极差，反映回波稳定性 |
| `roi_valid_px` | ROI 内返回有效深度的像素数，占比过低说明目标超出相机深度范围 |
| `sync_offset_ms` | 激光最新帧与相机帧的时间差，仅作参考，未做硬同步 |

## 几何换算

界面显示的是**模块到光斑落点的直线距离（斜距 r）**，既不是离地高度也不是株高。

光轴垂直向下时：

```
穗位高 = 设备离地高度 − r
```

光轴存在俯角 α 时：

```
穗位高 = 设备离地高度 − r · sin α
```

α 每偏差 1°，在 6 m 距离上高度误差约 10 cm，与雄穗本身尺寸同量级，因此斜视方案必须先标定 α。

## 已知限制

- 模块标称量程（4 m）为室内白板条件测得，户外强光叠加深色低反射目标时会显著衰减，实测需先行验证。
- 激光为 940 nm 近红外，肉眼不可见，定位光斑需借助深色卡纸遮挡法（移动卡纸观察读数跳变边界）。
- 光斑在 4 m 处直径约 21 cm，与单颗雄穗尺寸相当，回波为穗体与背景的混合结果。
- 相机帧时间戳与系统时间存在 USB 传输延迟，`sync_offset_ms` 未做偏置标定。

## 文件说明

| 文件 | 用途 |
|---|---|
| `dual_sync_gui.py` | 主界面，双传感器同步采集与记录 |
| `port_probe.py` | 串口自动识别 |
| `laser_reader.py` | 激光读数解析与统计 |
| `range_test.py` | 量程与稳定性分段测试 |
| `scan_bauds.py` | 全波特率扫描 |
| `detect_laser.py` | 初次接入探测 |
| `diag_laser.py` | 握手线与命令响应诊断 |
| `dtr_rts_scan.py` | DTR/RTS 组合排查 |
| `live_watch.py` | 实时监听原始字节 |
| `loopback_test.py` | 串口板回环自检 |
| `install_deps.bat` | 依赖安装与校验 |
| `start.bat` | 一键启动 |
