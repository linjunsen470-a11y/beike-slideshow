# ke-slideshow

把贝壳房源资料和照片制作成 9:16 竖屏幻灯片视频，默认 1080×1920、30 fps、15–20 秒。抓取和渲染均不调用 LLM。

在本目录运行：

```bash
./make_video.sh <房源编号>
# 使用已有素材，固定模板与随机种子
./make_video.sh <房源编号> --skip-fetch --template editorial --seed 7
```

常用参数：

- `--skip-fetch`：复用已有房源目录，不访问贝壳。
- `--template gold_classic|editorial|poster|ledger|random`：金色经典、杂志、海报、账本或随机；脚本默认 `random`。
- `--seed N`：复现模板和 BGM 选择；省略时自动生成并打印种子。
- `--bgm <文件或目录>`：指定音乐来源；`--bgm-track <名称片段>` 指定曲目。默认按种子从 `bgm/user/` 随机选择，精简包仅附带 `bgm/user/`，未附带备用 `bgm/library/` 音乐库。
- `--force`：忽略抓取缓存重新抓取；`--city 城市`：优先查询城市（默认广州）；`--type auto|sale|new|rent`：房源类型。

输出目录为 `/workspace/ke-house-<id>/`：`listing.json` 和 `manifest.json` 保存资料与图片清单，`images/` 保存素材，`video/` 保存 `<拼音或house>_<id>_9x16_<模板>.mp4`、时间线 JSON 和预览图片。

贝壳密钥仅从 `~/.beike/BEIKE_MCP_API_KEY` 读取，不支持环境变量覆盖，也不会打印密钥。请自行在该文件配置密钥，不要提交到仓库。

依赖：Python 3、Bash、FFmpeg（含 ffprobe、libx264 和 AAC 编码支持），以及 Pillow、NumPy：

```bash
python3 -m pip install -r requirements.txt
```

可选：`librosa` 用于节拍分析（缺省使用 NumPy 回退），`pypinyin` 用于输出文件名拼音（缺省使用 `house`）。保留随附的 `fonts/`、`bgm/`、`sfx/` 和音频 `.analysis/` 缓存。

模板细节见 [TEMPLATES_PLAN.md](TEMPLATES_PLAN.md)，近期行为记录见 `REPORT_*.md`；精简包清理记录见 `REPORT_SLIM.md`。维护约定见 [AGENTS.md](AGENTS.md)。
