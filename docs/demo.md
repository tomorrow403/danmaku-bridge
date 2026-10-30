# 运行示例

以下输出由仓库内的离线固定响应（`fixtures/`）实际运行产生，不包含任何真实接口数据。

## 1. 检查凭证与请求策略

```console
$ python -m danmaku_bridge doctor
DanmakuBridge 0.4.0
AppId: 已配置 test***
AppSecret: 已配置
配置文件路径: ~/.config/danmaku-bridge/config.json
缓存文件路径: ~/.cache/danmaku-bridge/match-cache.json
请求策略: 串行、间隔 1s、单次运行上限 30 次请求
```

## 2. 先看要处理哪些文件（不发起任何请求）

```console
$ python -m danmaku_bridge scan /media/anime
共 2 个视频，其中 0 个已有同名 .ass
  [待处理] 示例作品 - 第01话.mkv  (8.0 MB)
  [待处理] 示例作品 - 第02话.mkv  (8.0 MB)
```

## 3. 预览执行计划（dry-run，不读指纹、不联网、不写文件）

```console
$ python -m danmaku_bridge run /media/anime --dry-run
[dry-run] 只显示处理计划：不读取指纹、不发起请求、不写入文件
  → 示例作品 - 第01话.mkv
      1) 计算文件指纹（head16m）
      2) POST /api/v2/match
      3) GET  /api/v2/comment/{episodeId}
      4) 写入 示例作品 - 第01话.ass
  → 示例作品 - 第02话.mkv
      1) 计算文件指纹（head16m）
      2) POST /api/v2/match
      3) GET  /api/v2/comment/{episodeId}
      4) 写入 示例作品 - 第02话.ass

计划处理 2 个文件，跳过 0 个，预计请求 4 次，间隔 1.0s
```

`--dry-run` 不需要 AppId，也不会产生任何网络流量，适合在正式执行前确认路径没有指错。

## 4. 生成字幕

```console
$ python -m danmaku_bridge run /media/anime --limit 20
√ 示例作品 - 第01话.mkv → 示例作品 第 1 话 · 写入 60 条

完成：生成 1，跳过 0，未识别 0，失败 0，本次请求 2 次
```

单集只产生 2 次请求：`/api/v2/match` 一次、`/api/v2/comment/{episodeId}` 一次。

## 5. 产物

输出的 `.ass` 与视频同目录、同名，媒体服务器会自动识别为外挂字幕：

```
/media/anime/
├── 示例作品 - 第01话.mkv
├── 示例作品 - 第01话.ass   ← 新增
└── 示例作品 - 第02话.mkv
```

## 6. 重复运行不会重复请求

```console
$ python -m danmaku_bridge run /media/anime
- 跳过（已存在字幕）：示例作品 - 第01话.mkv

完成：生成 0，跳过 1，未识别 0，失败 0，本次请求 0 次
```
