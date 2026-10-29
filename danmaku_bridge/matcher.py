"""媒体库扫描与文件指纹计算。"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Iterator, List, Optional

VIDEO_EXTS = {
    ".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mts",
    ".wmv", ".flv", ".mov", ".rmvb", ".rm", ".webm",
}

HEAD_SIZE = 16 * 1024 * 1024  # 前 16MB，与开放网络对文件指纹的约定一致


@dataclass
class MediaFile:
    path: str
    name: str
    size: int

    @property
    def ass_path(self) -> str:
        return os.path.splitext(self.path)[0] + ".ass"


def scan(root: str, recursive: bool = True) -> List[MediaFile]:
    """扫描目录下的视频文件，跳过隐藏文件与已存在字幕的同类文件。"""
    result: List[MediaFile] = []
    if os.path.isfile(root):
        if _ext(root) in VIDEO_EXTS:
            result.append(_make(root))
        return result

    walker: Iterator = os.walk(root) if recursive else [(root, [], os.listdir(root))]
    for dirpath, dirnames, filenames in walker:
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            full = os.path.join(dirpath, name)
            if _ext(full) in VIDEO_EXTS:
                result.append(_make(full))
    return result


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def _make(path: str) -> MediaFile:
    return MediaFile(path=path, name=os.path.basename(path), size=os.path.getsize(path))


def file_hash(path: str, mode: str = "head16m") -> Optional[str]:
    """计算文件指纹。

    head16m：仅读前 16MB，适合大文件的 NAS 场景（也是本工具默认值）。
    full   ：整文件 MD5，速度慢但更精确。
    none   ：不计算，改用「文件名 + 大小」匹配。
    """
    if mode == "none":
        return None
    algo = hashlib.md5()
    limit = HEAD_SIZE if mode == "head16m" else None
    with open(path, "rb") as fh:
        remaining = limit
        while True:
            chunk_size = 1024 * 1024
            if remaining is not None:
                chunk_size = min(chunk_size, remaining)
                if chunk_size <= 0:
                    break
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            algo.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    return algo.hexdigest()


def pick_episode(match_result: dict) -> Optional[dict]:
    """从识别响应中取最可信的一条结果。"""
    if not match_result.get("isMatched"):
        return None
    matches = match_result.get("matches") or []
    if not matches:
        return None
    return matches[0]
