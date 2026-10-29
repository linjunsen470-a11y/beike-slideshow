# 贝壳房源短视频工具

## 项目背景与目标

这是一个供个人和协作 Agent 使用的小工具：输入贝壳房源编号，将该房源的真实资料和照片制作成可比较、可交付的竖屏视频。用户已经认可五个推荐模板，后续维护应保留它们的视觉风格，减少重复操作、付费请求和无用文件。

项目不是通用视频平台。房源查询、文字排版、音乐分析和视频渲染使用确定性程序，不调用 LLM；只有用户选择的照片修补步骤会调用付费图像 API。默认输出为 1080×1920、30 fps 的 MP4，时长跟随所选音乐完整长度。

| 文档 | 应回答的问题 |
| --- | --- |
| 本文 README | 工具做什么、输入什么、怎样调用、输出在哪里、失败怎么办 |
| [TEMPLATES_PLAN.md](TEMPLATES_PLAN.md) | 五个模板分别是什么、哪些视觉约定应保留 |
| [AGENTS.md](AGENTS.md) | 人和 Agent 应如何维护、验证及保护本地数据 |
| [archive/README.md](archive/README.md) | 历史资料与当前说明如何区分 |

## 工作流与入口

```text
房源编号 + 城市
    ↓ fetch_listing.py（贝壳接口；可复用抓取缓存）
listing.json + manifest.json + images/
    ├──────────────────────────────────┐
    ↓ 可选 remote_edit_images.py       │ 原图直接渲染
images_remote/ + manifest_remote.json   │
    └──────────────────────────────────┘
    ↓ build_slideshow.py + 本地音乐 + 模板
video/*.mp4
```

`make_video.py` 将“抓取 → 渲染”串起来，**不会自动改图**。已有素材用 `--skip-fetch`；已有改图结果再加 `--edited`。`make_video.sh` 只是同一 Python 入口的 Bash 包装。

| 入口 | 输入 | 行为与输出 |
| --- | --- | --- |
| `fetch_listing.py HOUSE_ID` | 编号、城市、贝壳凭证 | 查询资料、下载照片，写入房源目录 |
| `remote_edit_images.py --house-dir DIR` | 原始 manifest、照片、改图凭证 | 可选付费修图，写入独立图片目录和 manifest |
| `build_slideshow.py --house-dir DIR` | 本地资料、照片、音乐 | 直接渲染，不联网抓取或改图 |
| `make_video.py HOUSE_ID` | 编号及抓取/渲染选项 | 抓取后渲染一条视频；未知参数转交渲染器 |
| `preview_composition.py --house-dir DIR` | 本地素材与模板 | 显式生成一张联系表，不生成视频 |

## 环境与凭证

- Python 3.9+；执行 `python -m pip install -r requirements.txt`。
- FFmpeg 与 ffprobe 加入 PATH，支持 H.264/AAC。
- 自备有使用权限的音乐，放到 `bgm/user/`，或通过 `--bgm-file` 指定文件。本地音乐、字体和房源数据不随 Git 仓库分发。
- 贝壳凭证仅从 `~/.beike/BEIKE_MCP_API_KEY` 读取，Windows 对应当前用户目录下的 `.beike/BEIKE_MCP_API_KEY`。不接受环境变量覆盖，不在命令行传入明文。
- 只有改图需要项目 `.env`：复制 `.env.example` 后填写 `IMAGE_EDIT_API_KEY`。不要覆盖已有 `.env`。该凭证与贝壳凭证是两套独立配置。

## 设置本次任务参数

以下是 **PowerShell** 示例，从仓库根目录执行。尖括号内容都是占位符，必须替换为本次任务的真实值；不代表固定房源或城市。`HOUSE_ID` 是至少六位数字的贝壳房源编号，不是小区编号。

先设置变量，后续命令复用它们：

```powershell
$houseId = '<贝壳房源编号>'
$city = '<房源所在城市>'
$workDir = Join-Path (Get-Location) 'data'
$houseDir = Join-Path $workDir "ke-house-$houseId"
$template = 'ad_photo_story_v20'
$musicFile = '<本地音乐文件的完整路径>'
```

`--work-dir` 是存放多个房源目录的父目录；`--house-dir` 是某一套房源目录；`--output` 是完整 MP4 文件路径，三者不要混用。脚本默认城市是广州，调用时应显式传入实际城市。

### 方式一：原图一键生成

```powershell
python -B make_video.py $houseId --city $city --work-dir "$workDir" --template $template --seed 7 --bgm-file "$musicFile"
```

已有素材、不想再次抓取时：

```powershell
python -B make_video.py $houseId --work-dir "$workDir" --skip-fetch --template $template --seed 7 --bgm-file "$musicFile"
```

### 方式二：先改图，再生成

逐条执行；每一步成功后再执行下一步。PowerShell 原生命令失败不会自动阻止手动执行后面的命令。

```powershell
# 1. 抓取；已有完整素材则跳过这一步
python -B fetch_listing.py $houseId --city $city --out-dir "$houseDir"

# 2. 查看待处理照片，不调用 API、不写文件
python -B remote_edit_images.py --house-dir "$houseDir" --dry-run

# 3. 付费改图，默认经济档、3 个并发；先用 2 张确认质量
python -B remote_edit_images.py --house-dir "$houseDir" --limit 2

# 4. 确认效果后处理剩余照片；已完成且有效的结果会复用
python -B remote_edit_images.py --house-dir "$houseDir"

# 5. 使用改图 manifest 渲染；不会再次调用改图 API
python -B make_video.py $houseId --work-dir "$workDir" --skip-fetch --edited --template $template --seed 7 --bgm-file "$musicFile"
```

不需要修图时，直接使用方式一，不必创建 `images_remote/`。

### 一次生成五个模板，同素材、同音乐

先完成一次抓取及所需的改图，再执行循环。下面使用改图结果；使用原图时删除 `--edited`。每个模板独立命名，不覆盖其他模板的视频。

```powershell
$templates = @('ad_masthead', 'ad_photo_story', 'ad_photo_story_v20', 'tour_route', 'cinema_immersive')
foreach ($name in $templates) {
    $videoFile = Join-Path $houseDir "video/${name}_1080p.mp4"
    python -B make_video.py $houseId --work-dir "$workDir" --skip-fetch --edited --template $name --seed 7 --font heiti --bgm-file "$musicFile" --width 1080 --height 1920 --fps 30 --output "$videoFile"
    if ($LASTEXITCODE -ne 0) { throw "生成失败：$name；已完成的视频保留。" }
}
```

Bash 用户同样传入实际编号和城市；变量语法与 PowerShell 不同：

```bash
house_id='<贝壳房源编号>'
city='<房源所在城市>'
music_file='<本地音乐文件的完整路径>'
./make_video.sh "$house_id" --city "$city" --template ad_photo_story_v20 --seed 7 --bgm-file "$music_file"
```

## 输出与常用选项

```text
data/ke-house-HOUSE_ID/
├── listing.json          房源事实
├── manifest.json         原始图片路径、角色和顺序
├── images/               原图
├── raw_*                 可复用的抓取缓存
├── images_remote/        可选：已修补图片
├── manifest_remote.json  可选：修补图与保留原图的混合清单
└── video/                视频输出
```

普通渲染仅输出 MP4；临时文件自动清理，编码成功后才替换目标视频。同一路径再次成功生成会覆盖旧视频，要留多个版本请指定不同 `--output`。

| 参数 | 所属入口与含义 |
| --- | --- |
| `--skip-fetch` | 一键入口：只用已有资料和图片 |
| `--edited` | 一键/预览入口：使用已存在的 `manifest_remote.json`，不触发改图 |
| `--force` | 抓取/一键入口：刷新抓取缓存；改图入口：重新付费处理已有图，两者含义不同 |
| `--scan-cities` | 抓取/一键入口：显式允许跨城市查询，默认关闭 |
| `--seed 7` | 渲染随机种子；相同环境及素材下可复现选择 |
| `--bgm-file PATH` | 明确指定同一首音乐；跨模板对比优先用它 |
| `--bgm-track TEXT` | 按名称片段选曲；`--bgm-random` 强制随机换歌 |
| `--workers N` | 改图入口控制 API 并发；渲染入口控制本地帧生成并发，两者互不关联 |
| `--limit N` | 仅改图入口：本次最多请求 N 张，0 表示所有待处理照片 |
| `--only FILENAME` | 仅改图入口：只处理 manifest 中指定的原图文件名 |
| `--diagnostics` | 渲染排障专用：额外产生预览图、时间线与审阅信息，平时不加 |

完整参数以各脚本的 `--help` 为准。正常任务不需要调用预览或诊断入口。

## 改图模型与费用边界

Gemini 默认经济档为 `gemini-3.1-flash-lite-image`（1K、minimal thinking）。经济档会覆盖旧 `.env` 的 Gemini 模型选择；要使用配置值，显式传 `--model configured`，也可传 `--model MODEL_ID`。OpenAI 兼容接口使用其配置模型。

每张最多一次请求，不自动重试、不升级模型。并发只减少等待时间，不减少请求费用。有效旧图会复用；源图更新会重新处理，单纯换模型不会重做旧图。户型图和 VR 封面不送去改图。部分失败时保留可用旧图/原图、更新 manifest 并返回非零退出码；需先检查失败项，不应把部分失败当作全部完成。

提示词要求只清除平台叠加水印、保留真实空间，但结果仍需人工检查。经济档不是固定折扣承诺，实时费用以 [Google 价格表](https://ai.google.dev/gemini-api/docs/pricing) 为准；不能凭模型名称推断总费用减半。

## 贝壳接入与当前限制

`beike_mcp.py` 是项目自带的 HTTP MCP 客户端，连接 `https://building.ke.com/mcp`。抓取主要使用 `entity_detail` 获取资料、`entity_material` 获取图片地址。`tools/list` 用于核对服务端工具，`python -B beike_mcp.py --list-tools` 会联网并读取凭证；`--help` 不会。

`--type sale/rent` 分别查询 `house/rent_house`。现有 `--type new` 只是把 house 结果标为新房展示顺序，并未实现独立新楼盘搜索，不要据此承诺支持任意新盘编号。

**最近实测状态（2026-10-29，不代表所有账号）：** MCP 握手可成功，但工具列表和详情请求返回 `invalid cli request`；官方 CLI 对当时的凭证提示无效或已过期。握手成功或 HTTP 200 都不能证明业务调用成功。当前这些凭证下的新房源抓取受阻，本地素材出片不受影响。经济档改图代码完成离线检查，但尚未进行真实付费质量验证。

遇到鉴权拒绝，应先用官方 CLI 核实并向服务方排查，不要自动轮换密钥、无限重试、猜测请求头或把问题归因于房源不存在。官方资料：[接入说明](https://github.com/LianjiaTech/beike-ai-platform)、[凭证说明](https://github.com/LianjiaTech/beike-ai-platform/blob/master/docs/authentication.md)。

## 代码职责与仓库边界

| 文件 | 维护职责 |
| --- | --- |
| `make_video.py` / `make_video.sh` | 总控参数、抓取/渲染串联；shell 仅转交参数 |
| `fetch_listing.py` / `beike_mcp.py` | 资料、图片、缓存 / MCP 请求、文件凭证 |
| `remote_edit_images.py` / `image_edit_api.py` | 并发任务、结果复用 / 图像 API 适配 |
| `build_slideshow.py` | 渲染 CLI、音乐准备、FFmpeg 输出 |
| `slideshow_templates.py` | 五个推荐模板的绘图函数 |
| `slideshow_layouts.py` | 文字度量、共享布局与历史模板兼容 |
| `slideshow_engine.py` | 镜头顺序、时间线、转场、帧合成 |
| `slideshow_common.py` | 字体、模板名单、图片加载与绘图基础 |
| `bgm_tools.py` / `sfx_tools.py` | 本地音频分析、缓存、音效 |
| `preview_composition.py` | 显式生成一张本地联系表 |

Git 保存源码、当前文档、配置示例和现有 `sfx/` 音效；不保存凭证、房源数据、成片、BGM、字体、下载客户端或历史压缩包。`.gitignore` 只控制入库，不删除本机文件。

文档维护记录（2026-10-29）：统一任务背景、变量占位符、三阶段流程和五模板调用；按实际 CLI 核对选项，检查本地文档链接与 Git 差异。此次不读取凭证、不联网抓房源、不改图、不渲染。
