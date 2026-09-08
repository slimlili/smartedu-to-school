# smartedu-grab — 国家中小学智慧教育平台资源校本化工具

将平台上人教版必修三各课时「学习任务单 / 课后练习」抓取并重排为校本资源：
分课时打印件、整章学生作业本 / 解析版、16:9 翻页 HTML 讲义。

**交付归档见 `~/Downloads/必修三校本资源/`（及总包 `必修三校本资源_完整包.zip`）**。
本项目目录保留：脚本 + 平台原始 PDF(`out/`)，供继续扩展第九章等使用。

## 目录

- `out/` — 平台原始 PDF（必修三整册已抓，按 章/节/课时 组织）
- `reflow_10 ~ reflow_13/` — 正式打印件（每课时：任务单 学生/解析 + 练习 学生/解析/答案）
- `out_merged/` — 整章合并：`第X章_学生用作业本.pdf`（无答案）、`第X章_解析版.pdf`（含逐题+任务解析）
- `out_deck*` — 16:9 翻页 HTML 讲义 + index
- `secret/` — 平台登录 token（**含个人凭证，勿分享；过期后需重新获取**）
- `work/` — 抓取中间 JSON（教材树/章节清单等）

## 脚本

| 脚本 | 作用 |
|---|---|
| `grab_book.py` | 整册下载（按章组织）到 `out/` |
| `sget.py` | 平台鉴权 GET（读 secret/nd_auth.json） |
| `retypeset.py` `textflow.py` `render_ws.py` | PDF → 结构化 → 校本 HTML（重排/公式/选项/作答区） |
| `task_answers.py` | 各学习任务参考解析库（含 `pick_task_answer` 匹配） |
| `build_all_reflow.py <章目录> <输出目录>` | 生成某章分课时打印件 |
| `merge_book.py`(章10) `merge_book_11/12/13.py` | 生成整章 学生作业本 + 解析版（经环境变量 MB_REF/MB_OUT） |
| `deck_all.py <章目录> <输出目录>` | 生成某章 16:9 讲义 |
| `make_index.py` | 生成章资源索引 |

## 复用到其他章/册

1. 换教材 ID → `grab_book.py` 抓取到 `out/`
2. `build_all_reflow.py "<章名>" reflow_XX` 生成打印件
3. `MB_REF=$PWD/reflow_XX ... python3 merge_book_XX.py` 生成合并册
4. `deck_all.py "<章名>" out_deck_XX` 生成讲义
5. 在 `task_answers.py` 补该章课时学习任务解析

## 微课视频 / 逐字稿（2026-09 新增）

- **`batch_video.py`** 批量下载微课视频为 mp4
  `python batch_video.py <courses_dir> <输出目录> [清晰度flag,默认href-360p-m3u8]`
  分片解密可续传；已产 `~/Downloads/必修三微课视频/`（四章 31 个 360p mp4 + 各章 zip）
- **`transcript.py`** 单课微课 → 逐字稿 txt/srt（faster-whisper, small 模型, 简体）
- **`batch_transcript.py`** 批量逐字稿（已弃用方向，可复用）
- 各章 course json：`work/courses10 ~ courses13/`（含每课时微课 m3u8）
- 注：模型经 `HF_ENDPOINT=https://hf-mirror.com` 下载（huggingface 直连不通）

## 命名约定

- 打印件：`<课时>_学习任务单_学生/解析`、`<课时>_课后练习_学生/解析/答案`
- 合并册：`第X章_学生用作业本.pdf`、`第X章_解析版.pdf`

> 依据「国家中小学智慧教育平台」公开资源整理重排，仅用于校内教学交流。
