# 贝壳房源短视频

从贝壳抓取房源资料和照片，用 Pillow + FFmpeg 生成 9:16 视频。抓取、字幕、音乐分析、渲染均不调用 LLM。AI 改图是独立的可选步骤。

> 当前状态（2026-10-29）：本地出片已验证；贝壳接口可握手，但工具访问返回 `invalid cli request`，官方 CLI 对现有凭证提示无效或已过期。在线抓取暂不可用，先使用已有素材。改图经济档尚未完成真实 API 质量验证。

## 快速使用

需要 Python 3.9+、FFmpeg/ffprobe（加入 PATH），然后安装 `pip install -r requirements.txt`。
贝壳密钥只放在 `~/.beike/BEIKE_MCP_API_KEY`；不得放进环境变量或项目文件。

```powershell
# 抓取并生成；所有系统默认使用项目 data/ke-house-<id>/
python make_video.py 108406164038 --city 广州

# 使用已有素材，固定模板、排版种子和音乐
python make_video.py 108406164038 --skip-fetch --template cinema_immersive --seed 7

# 使用已经改好的图片；此命令不会调用改图 API
python make_video.py 108406164038 --skip-fetch --edited --template ad_photo_story_v20

# Linux/macOS 同样参数，由 shell 转交同一个 Python 入口
./make_video.sh 108406164038 --skip-fetch --template tour_route
```

`--work-dir` 可以更换数据根目录；已有 `/workspace/ke-house-<id>/` 的机器传 `--work-dir /workspace`。
默认仅写最终 MP4，临时音频和编码文件会清理，编码成功后才替换目标视频。
默认同模板输出路径会被下一次成功生成覆盖；要留多版请传不同的 `--output`。

## 五个推荐模板

默认 `random` 只从以下五个模板选择。历史模板仍可按原名称显式指定。

| 名称 | 用途 |
| --- | --- |
| `ad_masthead` | 深绿刊头、大图广告 |
| `ad_photo_story` | 奶油底实拍画报 |
| `ad_photo_story_v20` | 看房叙事、紧凑边距（保留现有 v23 视觉） |
| `tour_route` | 漫游路线、空间节点 |
| `cinema_immersive` | 满屏实拍、金白叠字 |

`python build_slideshow.py --list-templates` 查看推荐名称；版式约定见 [TEMPLATES_PLAN.md](TEMPLATES_PLAN.md)。

常用参数：`--seed 7` 固定随机选择；`--font heiti` 指定字体；`--bgm-track 名称片段` 固定音乐；`--bgm-random` 强制换歌；`--sfx off` 关闭音效；`--workers 3` 控制本地渲染并发。
默认完整播放选中音乐，镜头适配音乐时长，不截取、不循环；保留 `bgm/user/` 和 `.analysis/` 缓存。

## 可选改图

将 `.env.example` 复制为 `.env`，填入 `IMAGE_EDIT_API_KEY`。这是改图凭证，与贝壳密钥独立。

```powershell
# 先看哪些图需要请求，不调用 API、不写文件
python remote_edit_images.py --house-dir data/ke-house-108406164038 --dry-run

# 默认 3 个并发请求；本次最多付费处理 2 张
python remote_edit_images.py --house-dir data/ke-house-108406164038 --limit 2

# 只修指定照片
python remote_edit_images.py --house-dir data/ke-house-108406164038 --only 07_客厅_1.jpg
```

- Gemini 默认经济档 `gemini-3.1-flash-lite-image`，1K、minimal thinking。即使旧 `.env` 配有别的 Gemini 模型，也默认使用经济档；`--model configured` 才遵循 `.env` 模型，或用 `--model <模型ID>` 明确选择。
- 保持单张输入、单张输出；不自动升级模型、不自动重试。`--limit N` 控制本次最大请求数，0 表示所有待处理照片；并发范围 1–8。并发缩短等待时间，不减少单张费用。
- 已有有效图片可复用；源图更新后重做。更换模型不会自动重做旧图；`--force` 会重新付费。
- 户型图、VR 封面不送去改图。每张完成后更新同一个 `manifest_remote.json`；部分失败保留可用旧图/原图并返回非零退出码。
- OpenAI 兼容接口仍支持：设置 HTTPS `/v1/images/edits` endpoint 和模型。经济档不会替换该接口的模型。
- 提示词仅要求清除平台叠加水印，但模型仍可能改动真实细节，使用前人工看图。需先用少量照片确认质量。

按 2026-10-29 核对的 [Google 价格表](https://ai.google.dev/gemini-api/docs/pricing)，Flash Lite Image 和 Nano Banana 2.1 的 1K 图像输出均约 $0.0336/张；Lite 的输入、文字/思考单价更低。不能把经济档说成总费用固定减半。模型信息见 [官方图像说明](https://ai.google.dev/gemini-api/docs/image-generation)。

## 贝壳接口是什么

`beike_mcp.py` 是本项目的直接 HTTP MCP 客户端，连接 `https://building.ke.com/mcp`，并非通过聊天模型代理请求。

| 工具 | 用法 |
| --- | --- |
| `entity_detail` | 查询房源基础信息及关联小区资料；参数 `entity_ids`、`entity_type`、`city_name` |
| `entity_material` | 获取房源/户型/小区图片地址；另带 `fields` |
| `tools/list` | 建连时核对上述工具是否存在；不臆造服务端能力 |

`python beike_mcp.py --list-tools` 可主动联网查看实际工具名和参数（会读取贝壳密钥）；`--help` 不联网。
`fetch_listing.py` 默认只查 `--city` 指定城市，找不到可显式加 `--scan-cities`。`--force` 刷新缓存。
`--type sale/rent` 对应 `house/rent_house`；现有 `new` 只给返回的 house 标记为新房展示顺序，不是独立的新楼盘搜索接口。
`raw_*` 是可复用的抓取缓存；`listing.json` 是房源事实；`manifest.json` 是图片顺序与路径，均保留。

## 维护位置

| 文件 | 职责 |
| --- | --- |
| `make_video.py` / `.sh` | 一键串联抓取与渲染；shell 只转交参数 |
| `fetch_listing.py` / `beike_mcp.py` | 抓取缓存、下载 / MCP 协议与文件密钥 |
| `remote_edit_images.py` / `image_edit_api.py` | 改图任务并发、缓存 / API 请求适配 |
| `build_slideshow.py` | 渲染参数、音乐准备、FFmpeg 输出 |
| `slideshow_templates.py` | 五个推荐模板的绘图函数，日常样式改这里 |
| `slideshow_layouts.py` | 文字度量、共享布局和历史模板兼容 |
| `slideshow_engine.py` | 镜头顺序、时间线、转场、帧合成 |
| `slideshow_common.py` | 字体、模板名单、绘图基础与图片加载 |
| `bgm_tools.py` / `sfx_tools.py` | 本地音乐分析缓存与音效 |
| `preview_composition.py` | 显式生成一张联系表 |

只需看图时运行：

```powershell
python preview_composition.py --house-dir data/ke-house-108406164038 --template ad_photo_story_v20
```

仅排障时给渲染器加 `--diagnostics`：输出预览 PNG、详细时间线并执行审阅检查；不再自动“修复”选中的转场。`--text-bounds warn/strict` 可单独开启文字检查，默认关闭。
历史报告和旧审阅脚本见 [archive/README.md](archive/README.md)，不参与正常运行。无需 CI、框架或测试矩阵。

## 仓库与本地文件

Git 仅保存源码、当前文档、配置示例和已有 `sfx/` 音效。房源图片、改图结果、视频、原始抓取缓存、BGM、字体、下载的官方客户端及历史压缩包均留在本机，不随克隆分发。新机器需自行准备音乐和字体；本地数据不受 `.gitignore` 影响，也不会因此删除。

根目录文档分工：README 说明使用方式；TEMPLATES_PLAN 记录当前视觉约定；AGENTS 记录维护规则。历史任务与报告只放在本地归档中，不再新增逐次内审报告。

2026-10-29 清理记录：归并旧任务和报告、移除重复预览入口 `dump_plates.py`（改用 `preview_composition.py`），收紧凭证/生成物忽略规则；保留五个推荐模板、旧模板显式兼容及素材。维护检查仅做 Python 语法、CLI 帮助和 shell 语法检查，不联网抓取、不调用改图 API、不重复渲染。
