"""工作台范围与浏览器渲染回执；回执不是执行授权。仅使用标准库。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import secrets
import threading
import time


@dataclass(frozen=True)
class StudioScope:
    project: Optional[Path] = None
    workflow: str = 'graph.yaml'
    chapter: Optional[int] = None


def contained_path(root: Path, value: str) -> Path:
    """真实路径包含关系，避免 /novel-other 前缀和符号链接绕过。"""
    root = root.resolve()
    target = (root / value).resolve()
    target.relative_to(root)  # 越界抛 ValueError，调用方转换为 HTTP 403。
    return target


class ReadySessions:
    """每次启动独立 nonce、过期时间与渲染版本，不持久化运行权限。"""

    def __init__(self, ttl=600, capacity=128, clock=time.monotonic):
        self.ttl = ttl
        self.capacity = capacity
        self.clock = clock
        self._sessions = {}
        self._lock = threading.Lock()

    def _prune(self):
        now = self.clock()
        for key in list(self._sessions):
            if self._sessions[key]['expires'] <= now:
                del self._sessions[key]

    def _view(self, key, entry, revision):
        return dict(entry['context'], launch_id=key, revision=revision,
                    status='ready' if entry['rendered'] == revision else 'pending')

    def create(self, revision, context):
        with self._lock:
            self._prune()
            while len(self._sessions) >= self.capacity:
                del self._sessions[next(iter(self._sessions))]
            key = secrets.token_urlsafe(24)
            entry = {'context': dict(context), 'rendered': None,
                     'expires': self.clock() + self.ttl}
            self._sessions[key] = entry
            return self._view(key, entry, revision)

    def get(self, launch_id, revision):
        with self._lock:
            self._prune()
            return self._view(launch_id, self._sessions[launch_id], revision)

    def ack(self, launch_id, revision, current_revision):
        with self._lock:
            self._prune()
            entry = self._sessions[launch_id]
            if revision != current_revision:
                raise ValueError('工作流已变化，请加载最新配置后重新报告就绪')
            entry['rendered'] = revision
            return self._view(launch_id, entry, current_revision)
