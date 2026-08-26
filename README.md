# BiliTabCapture

将本地或哔哩哔哩的动态谱视频转换为PDF文件

相比[TabCapture](https://github.com/santiRostan/TabCapture)新增更多功能

## 新增功能

### 支持更多种类的视频
- 方便地拖拽上传本地文件
- 通过哔哩哔哩BV号导入视频
- 登录哔哩哔哩账号获取更高分辨率视频
- 谱面背景为彩色的视频
- 全屏动态谱视频
- 不同段落的谱面高度不一致的视频
- 从图片导入谱面进行排版

### 支持手动调整
- 调整图片缩放
- 裁切或删去截图，去除重复部分
- 补插两次截图间隔之间缺失的截图
- 图像反色，去除彩色背景，自定义背景及字体颜色
- 页边距，图片间距设置
- 图像水平和竖直的对齐设置
- 纸张横竖方向设置
- 标题支持非英文字符
- 实时预览调整效果
- 更方便的视频时间裁切及预览

### 其他功能
- 导出为长图
- 自动识别小节线
- 自动裁剪去重

## 声明

仅供学习与练习使用，若UP主提供谱面购买链接请勿使用本工具，尊重辛苦扒谱劳动成果

登录由[bilix](https://github.com/Koril33/bilix)处理，风险与本项目无关

## 致谢

- [santiRostan/TabCapture](https://github.com/santiRostan/TabCapture) 项目框架及截图算法
- [Koril33/bilix](https://github.com/Koril33/bilix) 哔哩哔哩视频下载，有部分改动，详见[m1ku666/bilix](https://gitee.com/m1ku666/bilix)
- [Carrot-shreds/score_capture](https://github.com/Carrot-shreds/score_capture) 自动识别小节线及裁剪去重

## 配置

需要 **Python >= 3.10**（requirements.txt 中的 yt-dlp 固定安装自 GitHub master 分支，
以避免 PyPI 正式版更新滞后于 YouTube 改动导致下载失败，而该分支要求 Python >= 3.10）。

### Windows

打包好的 `BiliTabCapture.exe` 双击即可运行，无需安装 Python。自行打包请运行
`build_exe.bat`，产物在 `dist/BiliTabCapture.exe`。

从源码运行：

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

### macOS / Linux

暂无打包好的可执行文件，需要从源码运行。仓库自带的 `bilix.exe` 是 Windows
专用二进制，无法在这两个平台上执行；程序会自动改用 `bilix_client.py`（纯
Python 实现的哔哩哔哩扫码登录与下载），功能上没有区别。

需要先装好 [ffmpeg](https://ffmpeg.org/)（用于合并哔哩哔哩下载的音视频流）：

```bash
brew install ffmpeg   # macOS
```

安装依赖并启动：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

浏览器会自动打开 <http://127.0.0.1:5000>。如果打不开或提示端口被占用，大概率是
macOS 自带的 AirPlay 接收器占用了 5000 端口（系统设置里关掉即可，或换个端口）：

```bash
PORT=5877 python app.py
```
