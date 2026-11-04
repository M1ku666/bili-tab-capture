# BiliTabCapture

将本地、哔哩哔哩或 YouTube 的动态谱视频转换为PDF文件

相比[TabCapture](https://github.com/santiRostan/TabCapture)新增更多功能

## 新增功能

### 支持更多种类的视频
- 方便地拖拽上传本地文件
- 通过哔哩哔哩BV号导入视频
- 登录哔哩哔哩账号获取更高分辨率视频
- 通过 YouTube 链接导入视频（基于 [yt-dlp](https://github.com/yt-dlp/yt-dlp)，最高 1080p，无需 ffmpeg）
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

## 致谢

- [santiRostan/TabCapture](https://github.com/santiRostan/TabCapture) 项目框架及截图算法
- [Carrot-shreds/score_capture](https://github.com/Carrot-shreds/score_capture) 自动识别小节线及裁剪去重

## 从源码运行

安装依赖
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

运行
```bash
python app.py
```

## YouTube 说明

- 在导入框粘贴 YouTube 链接即可（支持 `watch?v=`、`youtu.be/`、`shorts/` 等格式，或 11 位视频 ID）。
- 只下载单条视频轨（优先 H.264 mp4）和一条 m4a 音轨（导出 `.psz` 时作为伴奏），不需要安装 ffmpeg。
- 若提示 “Sign in to confirm you're not a bot”，可将浏览器导出的 Netscape 格式 cookies 保存为程序目录下的 `youtube_cookies.txt` 后重试。
- YouTube 经常调整接口，下载失败时请先升级 yt-dlp：`pip install -U yt-dlp`。新版 yt-dlp 可能还需要安装 JS 运行时（如 [deno](https://deno.com)），详见 yt-dlp 文档。
- 命令行同样支持：`python tab_extractor.py "https://youtu.be/VIDEO_ID" --output out.pdf`

## 打包

| 平台    | 脚本          | 产物                    |
| ------- | ------------- | ----------------------- |
| Windows | build_exe.bat | dist/BiliTabCapture.exe |
| macOS   | build_mac.sh  | dist/BiliTabCapture_mac |

