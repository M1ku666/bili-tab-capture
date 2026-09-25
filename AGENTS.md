# AGENTS.md

本文件为在本仓库工作的 AI/工程师提供上下文。**先读本文件，再动手改代码。**

## 文档维护约定（重要）

- **新增功能后，必须先向用户确认，再把该功能的说明补进本文件**（模块职责、缓存结构、约定与坑、常用命令等对应章节）。**不要未经确认就自行写入。**
- 修改既有行为时同理：先确认，再同步更新本文件里已经过时的描述。
- 本文件是项目上下文的唯一事实来源；`CLAUDE.md` 已并入本文件。

## 项目是什么

BiliTabCapture：把**动态谱视频或乐谱文档**（哔哩哔哩视频 / 本地视频 / 图片 / PDF）转换为 PDF/长图的工具，主要用于制谱截图。

- 后端：Flask 本地 Web 服务（`app.py`），默认 `http://127.0.0.1:5000`，启动后自动开浏览器。
- 前端：`templates/index.html` + `static/app.js` + `static/styles.css`（原生 JS，无框架）。
- 流程四步：**导入 → 截图(第2步) → 调整裁剪/小节线(第3步) → 排版导出(第4步)**。
- 四类源：B站视频(`bilibili`) / 本地视频(`local`) / 图片(`image`) / PDF(`pdf`)。
  其中 `image` 与 `pdf` 在“卡片/截图”层面**共用同一套逻辑**（`app.IMAGE_LIKE_TYPES`），
  区别只在缓存目录、渲染方式与第 2 步的取值单位。

## 目录与模块职责

| 文件 | 职责 |
| --- | --- |
| `app.py` | Flask 服务与全部 HTTP 路由；任务(Job)/源(Source)内存管理；缓存与历史记录；PDF/长图导出。 |
| `tab_extractor.py` | 视频抽帧、去重、裁剪、小节线识别、长图/PDF 绘制；**同时也可作为独立 CLI** (`python tab_extractor.py <url/文件>`)。 |
| `bili.py` | 哔哩哔哩扫码登录(二维码)与视频下载。**所有平台统一走这里**，不使用 `bilix.exe`/yt-dlp。 |
| `pdf_render.py` | **PDF 渲染**：`render_pdf_pages` 批量逐页渲染、`render_pdf_page` 单页渲染、`pdf_page_count` 探页数、`clamp_dpi` 收敛 DPI（50–600，默认 200）。依赖 PyMuPDF，**延迟导入**——缺依赖时只有真正导入 PDF 才报错，视频/图片不受影响。 |
| `runtime_paths.py` | 打包(PyInstaller)与源码运行时的路径解析：`resource_dir()`(只读资源)/`data_dir()`(可写数据, cookie/缓存)。 |
| `static/app.js` | 前端全部逻辑（导入、预览、裁剪、小节线、排版、上传、历史记录、更新检查、复位图标等）。 |
| `static/icons/*.svg` | 工具栏/按钮图标，均为独立 SVG 文件，**直接改文件即可替换图形**（`loadIcons()` 读取）。 |
| `build_exe.bat` / `build_mac.sh` | 一键打包（免环境运行）。产物写入 `dist/`。 |
| `VERSION` | 版本号，渲染进页面；更新检查用它比较。 |

## 数据与缓存结构（`BiliTabCapture_cache/`）

**持久缓存（可恢复进度；不要在清理逻辑里误删）**
- `bv/<bvid>/`：B 站视频。含下载的视频文件（`.m4s` DASH 视频轨，或回退的 `.mp4`）、`crops/`(截图)、`state.json`。
- `local/<hash>/`：本地视频（按文件内容 SHA-256 哈希）。
- `img/<hash>/`：图片（`master.*` 原图 + `crops/` + `state.json`）。
- `pdf/<hash>/`：PDF（按文件内容 SHA-256 哈希）。含：
  - `master.pdf` 原文件；
  - `pages/`：**按当前 DPI 渲染的整份 PDF 逐页位图**（`page_0001.png`…），带 `.dpi<N>.txt` 版本戳，DPI 变化时整体重渲；
  - `crops/`：裁剪后的截图（一页一张，即第 3 步的卡片）；
  - `state.json`。

**中间产物（不参与恢复，可安全清理）**
- `runs/<job_id>/`：一次“生成截图/导出”的工作目录（`crops/`、`final/`、导出的 PDF/长图）。
- `uploads/<source_id>/`：导入上传的中转副本。
- `previews/`：预览帧 jpg 与 B 站预览视频。

**`state.json` 关键字段**：`captures`(截图列表)、`images`(前端卡片状态：裁剪/隐藏/小节线)、`capture_params`、`metadata`(标题/作者/来源)、`layout`、`maxStage`、`params2`(第 2 步截图参数，见下)。PDF 额外有 `pdf_dpi`(渲染分辨率)、`page_count`(总页数)、`page_range`(`{start,end}` 页码区间)。

## 关键约定与“坑”（务必遵守）

1. **下载清晰度/角标以“实测”为准**：不要用 B 站返回的 qn 标签当作真实清晰度（会出现“标 1080P60 实际很糊”）。下载后写 `.dlqh.txt`（OpenCV 实测帧高），预览角标优先用它；`.dlqn.txt` 仅为回退。
2. **DASH 视频轨即可**：制谱只需画面。`bili.py` 从视频页 SSR(`__playinfo__`) 取 DASH **视频轨(codecid=7/AVC)** 直接下 `video.m4s`，**不下载音频、不做 ffmpeg 合并**。OpenCV 可直接读取 `.m4s`。SSR 拿不到时才回退单文件 `durl` 接口。
3. **登录态可能触发防盗链 404**：个别视频带登录 cookie 请求高清直链会 404/403，游客反而可用。下载逻辑需保留「先登录→失败退游客」的重试与逐档降清晰度。
4. **`.m4s` 是一等公民**：新增/修改“视频文件”识别时，务必把 `.m4s` 一并纳入（`tab_extractor.VIDEO_FILE_EXTENSIONS`、`app.ALLOWED_VIDEO_EXTENSIONS`、历史记录 `_playable`、前端 `accept` 与 `isImportableFile`）。漏掉会导致历史记录灰显、导入提示不支持。
5. **历史记录 = 直接遍历缓存目录**：目的是“管理本地存储占用”，**不能用 `state.json` 是否存在来筛选**——只下载未截图的目录也要列出（标题缺失时回退为 key）。恢复时：有截图态→复原卡片/排版；无截图态→进入第 2 步并回填 `params2`。
6. **第 2 步参数提前持久化**：截图参数（起止时间、采样间隔、差异阈值、条带半宽、比较窗口、去色容差/平滑、抽帧前裁剪框 `crop*`）通过 `POST /api/save_capture_prefs` 存进 `state.json` 的 `params2`（改动即存、防抖）。读取时 `read_capture_prefs()` 会为缺失字段**回退默认值以兼容旧版缓存**。
7. **“从新开始”（命中弹窗）会删除整个缓存目录**（`/api/cache_clear` + `full:true`）：之后必须避免继续引用已删除的文件（B 站会重新导入下载，本地/图片则回到第 1 步让用户重选）。
8. **中文标题字体**：PDF/长图的标题渲染依赖跨平台 CJK 字体查找（`tab_extractor.load_font`）。修改字体逻辑要保证 macOS（Hiragino/Songti/STHeiti）与 Windows（msyh 等）都能命中，否则中文会变“豆腐块”。
9. **端口被占自动顺延**：`app.py` 的 `__main__` 会在 5000 被占（macOS AirPlay）时自动换端口；`BTAB_NO_BROWSER=1` 可禁止自动开浏览器。
10. **更新检查走后端代理**：浏览器直连 Gitee API 会 403/CORS。前端只请求同源 `GET /api/latest_version`（后端依次尝试 Gitee tags → GitHub releases）。
11. **PDF 与图片共用卡片逻辑**：`app.IMAGE_LIKE_TYPES = {"image", "pdf"}`。凡是判断“非视频源”，**必须用 `IMAGE_LIKE_TYPES` 而不是 `== "image"`**（如 `/api/captures` 分流、`/api/source_image`）。漏掉会导致 PDF 走视频抽帧分支直接报错。前端对应的是 `state.sourceType`。
12. **第 2 步时间轴是双单位的**：视频按「秒」、PDF 按「页」，共用同一条轨道/把手/进度条。前端用 `state.timeUnit`（`"sec"`/`"page"`）与 `isPageMode()` 切换，取值走 `currentStartTime()/currentEndTime()`，换算走 `timeToRatio()/ratioToTime()`。页模式用 `(page-1)/(total-1)` 让首尾页贴住两端。**新增第 2 步参数要同步 `STEP2_PARAM_IDS` + `collectStep2Params()` + `applyStep2Params()`**，否则改动不会持久化。
13. **PDF 预览复用 `/api/preview`**：请求体里 `time` 对 PDF 是**页号**（1 基），后端渲染该页并缩成 jpg 返回，结构与视频预览完全一致——前端不必为 PDF 分叉预览逻辑。
14. **PDF 渲染缓存按 DPI 失效**：`pdf/<hash>/pages/` 存整份渲染图，用 `.dpi<N>.txt` 当版本戳；改 DPI 必须整体重渲（`_pages_complete()` 逐页校验，缺页即重渲）。`cache_clear` 非 full 分支也要清 `pages/`，否则「从新开始」后仍命中旧 DPI 图。
15. **缓存源（图片/PDF）的截图必须落 `cache/crops`**：`start_image_capture()` 的 `crops_dir` 取自 `cache_dir/crops` 并写 `state.json`；否则历史记录里该条目永远没有 `crops`、封面 404、无法恢复进度。`runs/<job_id>/crops` 只用于没有缓存目录的源。
16. **`.field[hidden]` 不生效**：`.field { display: grid }` 会覆盖 `hidden` 属性默认样式，样式表末尾有 `.field[hidden]/.time-field[hidden] { display: none !important }` 兜底。新增可隐藏字段给它加 `.field` 类即可生效。
17. **PyMuPDF 是新依赖**：`requirements.txt` 已加 `pymupdf`，两个 `.spec` 的 `hiddenimports` 也加了 `pymupdf`/`fitz`。**打包机器同样需要安装**，否则 PDF 导入会提示缺少支持库。

## 常用命令

```bash
# 开发运行（建议虚拟环境）
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
.venv/bin/python app.py                         # 打开 http://127.0.0.1:5000

# 仅当参数解析/抽帧算法改动时，用 CLI 快速验证
.venv/bin/python tab_extractor.py "<BV号或本地文件>" --output out.pdf

# 打包
build_exe.bat        # Windows → dist/BiliTabCapture.exe
bash build_mac.sh    # macOS   → dist/BiliTabCapture_mac

# 语法自检（无需运行 GUI）
.venv/bin/python -m py_compile app.py tab_extractor.py bili.py runtime_paths.py pdf_render.py
node --check static/app.js

# 造一个多页测试 PDF（不需要任何外部工具）
.venv/bin/python -c "
from PIL import Image
ps=[Image.new('RGB',(1240,1754),'white') for _ in range(5)]
ps[0].save('/tmp/t.pdf', save_all=True, append_images=ps[1:])"
```

## 修改指引

- 改后端路由/任务：先读 `app.py` 里相近的路由与 `JOBS/SOURCES` 的用法，保持异常都返回 `json_error(...)`。
- 改前端：`static/app.js` 顶部有 `els`（DOM 引用）与 `els` 之外的 `state`；新增 UI 记得在 `index.html` 加元素、在 `els` 注册，样式追加到 `styles.css` 末尾并复用主题变量（`--accent` / `--accent-weak` / `--accent-strong` / `--line` / `--input-bg` / `--muted` 等）。
- 图标：优先放 `static/icons/<name>.svg` 并在 `loadIcons()` 的映射中登记，不要在 JS 里内联大段 SVG（除非占位回退）。
- 依赖：保持精简（现为 Flask / numpy / opencv-python / Pillow / curl_cffi / qrcode / **pymupdf**）。**不要引入 ffmpeg 或新的重型依赖**，除非明确讨论过。
- **无头验证后端**：Flask 自带 `app.test_client()` 就能把整条链路跑通（导入→预览→生成截图→导出 PDF），不必开浏览器。记得 `BTAB_NO_BROWSER=1`，跑完清掉 `BiliTabCapture_cache/` 里的测试残留。

## 验证要求

- 至少跑上面的 `py_compile` 与 `node --check`。
- 涉及下载/清晰度：实际下载一个 B 站视频确认能被 OpenCV 打开并读出帧尺寸。
- 涉及缓存/历史：确认持久缓存 `bv/local/img/pdf` 不被误删，中间产物可被清理。
- 涉及 PDF：确认导入能拿到页数、改 DPI 会整体重渲、页码区间能正确产出对应页数的卡片。
- 无浏览器自动化环境时，明确说明“未运行 GUI，需人工点验”。
