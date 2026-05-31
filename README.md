# EVE Local Guard

一个 Windows 小工具，用来监控 EVE Online 本地频道成员列表里的威胁行。它只做屏幕截图识别，不读取游戏内存、不注入、不抓包。

判断规则：

- 蓝色、紫色、绿色标记：友方，不报警。
- 红色、橙色标记：威胁，报警。
- 没有蓝/紫/绿友方标记的玩家行：白名/中立，报警。

## 打包成 EXE

在 Windows 上安装 Python 3.10+，安装时勾选 `Add Python to PATH`。

然后双击：

```bat
build_windows_exe.bat
```

完成后 EXE 在：

```text
dist\EVELocalGuard.exe
```

## 没有 Windows 开发环境

macOS 不能直接用 PyInstaller 打出 Windows EXE。可以用 GitHub Actions 自动打包：

1. 新建一个 GitHub 仓库。
2. 把本目录所有文件上传到仓库。
3. 打开仓库的 `Actions` 页面。
4. 选择 `Build Windows EXE`。
5. 点 `Run workflow`。
6. 跑完后在页面底部下载 `EVELocalGuard-windows`。

下载的压缩包里会有：

```text
EVELocalGuard.exe
EVELocalGuardDebug.exe
```

正常用 `EVELocalGuard.exe`。如果双击没反应，运行 `EVELocalGuardDebug.exe`，并查看：

```text
%APPDATA%\EVELocalGuard\crash.log
```

## 使用方法

1. 打开 EVE，把本地频道成员列表放在固定位置。
2. 启动 `EVELocalGuard.exe`。
3. 点 `框选本地列表区域`，拖拽框住右侧成员列表。尽量只框玩家行，不要框频道标题、人数和聊天内容。
4. 点 `测试识别并保存截图`，检查是否能识别友方行和威胁行。
5. 点 `开始监控`。

## 参数建议

- `标记列X`：站位图标相对你框选区域左边的偏移。默认 `0`。
- `标记列宽`：扫描站位图标的宽度。默认 `0` 表示自动扫描左侧小图标区和右侧状态图标区；如果误判多，可以改成只覆盖实际图标列。
- `标记像素`：一行里至少多少个红/橙/蓝/紫/绿像素才确认有站位标记。误报多就调高，漏报就调低。
- `行内容像素`：多少亮色文字/头像像素才算一行玩家。标题被误识别时可以调高。
- `行合并`：同一玩家行中间允许有多少像素空隙。
- `确认帧`：连续多少帧都看到才报警。想更稳就设 `3`。
- `冷却(s)`：两次报警之间的最短间隔。

## 识别不到怎么办

先点 `测试识别并保存截图`。程序会在配置目录生成：

```text
last_capture.png
last_debug.png
```

`last_debug.png` 里黄色框是扫描的站位标记区域，绿色框是蓝/紫/绿友方行，红色框是红/橙威胁行，橙色框是白名/中立威胁行。  
如果黄色框没有覆盖站位图标，调整 `标记列X` 和 `标记列宽`。如果标题、人数被当成白名威胁，重新框选，只框玩家列表。

## 后续可加的功能

- OCR 识别具体角色名。
- 黑名单/白名单。
- ESI 登录读取联系人 standing。
- 托盘常驻。
- 语音播报。
