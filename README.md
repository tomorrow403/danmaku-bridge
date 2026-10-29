# DanmakuBridge

为 NAS / 媒体服务器批量生成**弹幕字幕（.ass）**的桥接工具。
扫描媒体库 → 识别视频对应的番剧剧集 → 拉取该集弹幕 → 输出同名字幕文件。

**本工具不包含播放器**：不播放视频、不内置播放内核、不替代任何客户端。
它只负责把弹幕转换成通用 ASS 字幕，交给 Jellyfin / Emby / Plex / VLC / mpv / PotPlayer
等你已经在用的播放端加载。

- 语言：Python 3.9+（标准库实现，无第三方依赖）
- 平台：Windows / macOS / Linux / NAS（Docker）
- 状态：可用（v0.3），持续维护

---

## 一、接入场景（谁在用、什么时候调用）

典型用户：在 NAS 上维护本地动画库、用 Jellyfin / Emby 观看的用户。
他们的痛点不是"缺少播放器"，而是**媒体库里没有弹幕**，而官方客户端无法覆盖 NAS 端的播放链路。

一次完整流程：

1. 用户在 NAS 上执行 `danmaku_bridge run /media/anime`（手动触发，非定时全库抓取）；
2. 工具遍历目录内的视频文件，对**每个文件**计算指纹（默认取前 16MB 的 MD5）；
3. 调用 `POST /api/v2/match`，用「文件名 + 文件大小 + 指纹」换取节目与剧集 ID；
4. 对识别成功的条目，调用 `GET /api/v2/comment/{episodeId}` 拉取该集弹幕；
5. 在本地把弹幕转换成 `.ass`，写到视频同目录、同文件名；
6. 媒体服务器扫描到新增字幕，播放时由播放端渲染。

调用量级（写死在代码里，不靠自觉）：

| 项目 | 取值 |
| --- | --- |
| 单集请求数 | **2 次**（match 1 次 + comment 1 次） |
| 请求方式 | 串行，两次请求之间间隔 ≥ 1 秒 |
| 单次运行文件数 | 默认 20，`--limit` 可调，用于分批处理 |
| 单次运行请求上限 | 默认 30 次，触顶即停止并提示分批运行 |
| 识别结果缓存 | 默认 6 小时（官方建议 2–6 小时） |
| 已存在字幕 | 直接跳过，不重复请求 |
| 预取 / 全库遍历 / 并发 | **不做** |

## 二、调用的接口

```text
POST /api/v2/match                    视频文件识别（fileName + fileSize + fileHash）
GET  /api/v2/comment/{episodeId}      获取指定剧集的弹幕
```

仅使用这两个**公开接口**，不涉及需要用户登录的受限接口（关注、播放历史、发送弹幕等），
不申请、不保存任何用户凭证或 JWT。

## 三、数据使用与合规设计

1. **只落本地**：识别结果与弹幕仅用于在本机生成 `.ass` 文件，不转发、不上传、不对外提供接口；
2. **不批量抓取**：单次运行有文件数与请求数双重上限，串行限速，触发上限即停止；
3. **不做镜像**：不复制弹幕库、不建立本地全量索引、不提供任何形式的数据导出服务；
4. **不规避限额**：只有一个 AppId，不做多凭证轮换，不代理他人请求；
5. **尊重缓存**：识别结果缓存 6 小时；已有字幕的文件不再请求；
6. **不采集用户数据**：无账号体系、无遥测、无统计上报。

## 四、安装与使用

```bash
git clone https://github.com/<your-name>/danmaku-bridge.git
cd danmaku-bridge

# 凭证：环境变量或配置文件，二选一（不要把 AppSecret 提交到仓库）
export DANDAN_APP_ID=your_app_id
export DANDAN_APP_SECRET=your_app_secret
# 或写入 ~/.config/danmaku-bridge/config.json: {"appId": "...", "appSecret": "..."}

python -m danmaku_bridge doctor              # 检查凭证与请求策略
python -m danmaku_bridge scan /media/anime   # 只列出待处理文件，不联网
python -m danmaku_bridge run  /media/anime   # 识别并生成 .ass
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--limit N` | 单次最多处理 N 个文件（默认 20） |
| `--max-requests N` | 单次请求上限（默认 30） |
| `--interval S` | 请求间隔秒数（默认 1.0） |
| `--hash-mode head16m\|full\|none` | 指纹计算方式 |
| `--max-comments N` | 单个文件最多写入的弹幕条数（默认 3000） |
| `--resolution 1920x1080` | 字幕分辨率，需与片源匹配 |
| `--overwrite` | 覆盖已存在的 `.ass` |
| `--mock` | 使用 `fixtures/` 固定响应离线验证，不发起网络请求 |

Docker（NAS 常用）：

```bash
docker build -t danmaku-bridge .
docker run --rm -v /volume1/anime:/media -e DANDAN_APP_ID=xxx -e DANDAN_APP_SECRET=yyy \
  danmaku-bridge run /media --limit 20
```

## 五、输出示例

运行 `docs/demo.md` 中的流程会得到与视频同名的字幕：

```
/media/anime/
├── 示例作品 - 第01话.mkv
├── 示例作品 - 第01话.ass   ← 新增
└── 示例作品 - 第02话.mkv
```

`docs/sample.ass` 是仓库内可直接查看的产物样例（由离线固定响应生成，非真实接口数据）。
字幕包含滚动弹幕的轨道分配、顶部/底部固定弹幕、颜色与描边，逐条带时间轴。

## 六、与官方产品的关系

| | 弹弹play 官方客户端 | DanmakuBridge |
| --- | --- | --- |
| 播放视频 | 是（内置播放内核） | **否**，只生成字幕文件 |
| 运行位置 | 桌面端 | NAS / 服务器 / 命令行 |
| 产物 | 实时叠加渲染 | 通用 `.ass` 字幕 |
| 面向用户 | 普通观众 | 自建媒体库的 NAS 用户 |

定位是补位：官方客户端覆盖不到的 NAS 播放链路，由本工具把弹幕"翻译"成播放端能读的字幕。
因此不重复实现播放、搜索、追番、发送弹幕等功能。

## 七、项目结构

```
danmaku-bridge/
├── danmaku_bridge/
│   ├── cli.py        # 命令行：scan / run / doctor
│   ├── client.py     # 签名、限速、请求上限、缓存
│   ├── matcher.py    # 目录扫描、文件指纹、识别结果解析
│   └── ass.py        # 弹幕 → ASS 字幕（轨道分配、样式、时间轴）
├── tests/            # 12 项单元与端到端测试（离线，不联网）
├── fixtures/         # 离线固定响应，用于测试与演示
├── docs/
│   ├── demo.md       # 实际运行记录
│   └── sample.ass    # 产物样例
├── Dockerfile
└── pyproject.toml
```

## 八、测试

```bash
python -m unittest discover -s tests -v
```

覆盖：签名算法、弹幕解析、ASS 生成（含顶部/底部/转义/去重）、目录扫描、指纹计算、
缓存过期，以及一次完整的离线端到端流程（扫描 → 识别 → 取弹幕 → 写 .ass → 重复运行跳过）。

## 九、开发日志

- 2026-10-29 v0.3 完成 ASS 渲染（轨道分配、颜色、描边、顶/底固定弹幕）
- 2026-10-29 v0.2 加入请求限速、单次上限、识别结果缓存与凭证占位机制
- 2026-10-29 v0.1 完成目录扫描、文件指纹、识别与弹幕拉取链路

## 十、声明

本项目为个人维护的非商业开源工具，免费使用，无会员、广告、赞助或任何收费点，
不将弹幕能力作为付费卖点。使用本工具时请遵守弹弹play开放弹幕网络的使用规定：
按需调用、合理缓存、不批量抓取、不做镜像、不用于商业用途。
