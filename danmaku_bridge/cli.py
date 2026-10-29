"""命令行入口：扫描媒体库 → 识别 → 取弹幕 → 生成 .ass。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from . import __version__
from .ass import build_ass, load_comments
from .client import ApiClient, ApiError, BudgetExceeded, MatchCache, MockClient, RequestPolicy
from .matcher import file_hash, pick_episode, scan

CONFIG_PATH = os.path.expanduser("~/.config/danmaku-bridge/config.json")
CACHE_PATH = os.path.expanduser("~/.cache/danmaku-bridge/match-cache.json")


def load_credentials() -> tuple[str, str]:
    app_id = os.environ.get("DANDAN_APP_ID", "")
    app_secret = os.environ.get("DANDAN_APP_SECRET", "")
    if app_id and app_secret:
        return app_id, app_secret
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        return cfg.get("appId", ""), cfg.get("appSecret", "")
    return "", ""


def cmd_scan(args: argparse.Namespace) -> int:
    files = scan(args.path, recursive=not args.no_recursive)
    if not files:
        print(f"未找到视频文件：{args.path}")
        return 1
    ready = sum(1 for f in files if os.path.exists(f.ass_path))
    print(f"共 {len(files)} 个视频，其中 {ready} 个已有同名 .ass")
    for f in files[: args.limit]:
        mark = "已有字幕" if os.path.exists(f.ass_path) else "待处理"
        print(f"  [{mark}] {f.name}  ({f.size / 1048576:.1f} MB)")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    app_id, app_secret = load_credentials()
    print(f"DanmakuBridge {__version__}")
    print(f"AppId: {'已配置 ' + app_id[:4] + '***' if app_id else '未配置'}")
    print(f"AppSecret: {'已配置' if app_secret else '未配置'}")
    print(f"配置文件路径: {CONFIG_PATH}")
    print(f"缓存文件路径: {CACHE_PATH}")
    print("请求策略: 串行、间隔 1s、单次运行上限 30 次请求")
    return 0 if app_id and app_secret else 2


def cmd_run(args: argparse.Namespace) -> int:
    files = scan(args.path, recursive=not args.no_recursive)
    if not files:
        print(f"未找到视频文件：{args.path}")
        return 1

    cache = MatchCache(args.cache or CACHE_PATH, ttl=args.cache_ttl)

    if args.mock:
        client = MockClient(args.mock_dir)
        print(f"[mock] 使用本地固定响应，不发起任何网络请求：{args.mock_dir}")
    else:
        app_id, app_secret = load_credentials()
        policy = RequestPolicy(min_interval=args.interval, max_requests=args.max_requests)
        client = ApiClient(app_id, app_secret, policy=policy)

    done = skipped = unmatched = failed = 0
    for media in files[: args.limit]:
        if os.path.exists(media.ass_path) and not args.overwrite:
            skipped += 1
            print(f"- 跳过（已存在字幕）：{media.name}")
            continue

        try:
            payload: Optional[dict] = cache.get(media.name, media.size)
            if payload is None:
                payload = client.match(media.name, media.size, file_hash(media.path, args.hash_mode))
                cache.put(media.name, media.size, payload)

            episode = pick_episode(payload)
            if not episode:
                unmatched += 1
                print(f"× 未识别：{media.name}")
                continue

            data = client.comments(int(episode["episodeId"]), with_related=args.with_related)
            comments = load_comments(data)
            if not comments:
                unmatched += 1
                print(f"× 无弹幕：{media.name}")
                continue

            text, count = build_ass(
                comments,
                play_res_x=args.res_x,
                play_res_y=args.res_y,
                max_comments=args.max_comments,
            )
            with open(media.ass_path, "w", encoding="utf-8") as fh:
                fh.write(text)
            done += 1
            title = episode.get("animeTitle", "")
            ep = episode.get("episodeTitle", "")
            print(f"√ {media.name} → {title} {ep} · 写入 {count} 条")

        except BudgetExceeded as exc:
            print(f"! {exc}")
            print(f"  已处理 {done} 个文件，其余保留待下次运行。")
            break
        except ApiError as exc:
            failed += 1
            print(f"× 接口错误：{media.name} · {exc}")
        except OSError as exc:
            failed += 1
            print(f"× 文件读写失败：{media.name} · {exc}")

    print(
        f"\n完成：生成 {done}，跳过 {skipped}，未识别 {unmatched}，失败 {failed}，"
        f"本次请求 {client.calls} 次"
    )
    return 0 if done else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="danmaku-bridge",
        description="为 NAS 媒体库生成弹幕字幕（.ass）的桥接工具，不内置播放器。",
    )
    parser.add_argument("--version", action="version", version=f"DanmakuBridge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="只列出待处理的视频文件，不发起任何请求")
    p_scan.add_argument("path")
    p_scan.add_argument("--limit", type=int, default=20)
    p_scan.add_argument("--no-recursive", action="store_true")
    p_scan.set_defaults(func=cmd_scan)

    p_run = sub.add_parser("run", help="识别并生成 .ass 字幕")
    p_run.add_argument("path")
    p_run.add_argument("--limit", type=int, default=20, help="单次最多处理的文件数，默认 20")
    p_run.add_argument("--interval", type=float, default=1.0, help="请求间隔秒数，默认 1.0")
    p_run.add_argument("--max-requests", type=int, default=30, help="单次运行请求上限，默认 30")
    p_run.add_argument("--max-comments", type=int, default=3000, help="单个文件最多写入的弹幕数")
    p_run.add_argument("--resolution", default="1920x1080", help="字幕分辨率，如 1920x1080")
    p_run.add_argument("--hash-mode", choices=["head16m", "full", "none"], default="head16m")
    p_run.add_argument("--cache", default=None, help="自定义缓存文件路径")
    p_run.add_argument("--cache-ttl", type=int, default=6 * 3600, help="缓存有效期秒数")
    p_run.add_argument("--with-related", action="store_true", help="同时获取关联剧集弹幕")
    p_run.add_argument("--overwrite", action="store_true", help="覆盖已存在的 .ass")
    p_run.add_argument("--no-recursive", action="store_true")
    p_run.add_argument("--mock", action="store_true", help="使用 fixtures 固定响应，便于离线验证")
    p_run.add_argument("--mock-dir", default="fixtures")
    p_run.set_defaults(func=cmd_run)

    p_doc = sub.add_parser("doctor", help="检查凭证与请求策略")
    p_doc.set_defaults(func=cmd_doctor)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        w, h = str(args.resolution).lower().split("x")
        args.res_x, args.res_y = int(w), int(h)
    try:
        return args.func(args)
    except ApiError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130
