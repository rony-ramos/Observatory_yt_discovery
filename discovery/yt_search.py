from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any


class SearchDependencyError(RuntimeError):
    pass


class SearchExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchHit:
    video_id: str
    url: str
    title: str
    channel: str | None
    channel_id: str | None
    duration: int | None
    view_count: int | None
    comment_count: int | None
    upload_date: str | None
    live_status: str | None
    description: str | None = None
    channel_country: str | None = None


class YtDlpSearcher:
    def __init__(self, *, retries: int = 2, retry_base_seconds: float = 5.0) -> None:
        self.retries = retries
        self.retry_base_seconds = retry_base_seconds

    @staticmethod
    def _dependencies() -> tuple[Any, type[Exception]]:
        try:
            from yt_dlp import YoutubeDL
            from yt_dlp.utils import DownloadError
        except ImportError as exc:
            raise SearchDependencyError(
                "Falta yt-dlp. Instala las dependencias con: pip install -r requirements.txt"
            ) from exc
        return YoutubeDL, DownloadError

    def search(self, query: str, max_results: int) -> list[SearchHit]:
        YoutubeDL, DownloadError = self._dependencies()
        options = {
            "extract_flat": True,
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": False,
            "playlistend": max_results,
            "socket_timeout": 30,
        }

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with YoutubeDL(options) as ydl:
                    info = ydl.extract_info(
                        f"ytsearch{max_results}:{query}",
                        download=False,
                    )
                return self._to_hits(info)
            except DownloadError as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                delay = self.retry_base_seconds * (2**attempt) + random.uniform(0, 1)
                time.sleep(delay)

        raise SearchExecutionError(f"Fallo la busqueda {query!r}: {last_error}")

    def enrich(self, hit: SearchHit) -> SearchHit:
        YoutubeDL, DownloadError = self._dependencies()
        options = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": False,
            "noplaylist": True,
            "socket_timeout": 30,
        }

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with YoutubeDL(options) as ydl:
                    info = ydl.extract_info(hit.url, download=False)
                if not isinstance(info, dict):
                    raise SearchExecutionError(f"Metadatos vacios para {hit.video_id}.")
                return SearchHit(
                    video_id=hit.video_id,
                    url=hit.url,
                    title=info.get("title") or hit.title,
                    channel=info.get("channel") or info.get("uploader") or hit.channel,
                    channel_id=(
                        info.get("channel_id") or info.get("uploader_id") or hit.channel_id
                    ),
                    duration=_prefer_value(info.get("duration"), hit.duration),
                    view_count=_prefer_value(info.get("view_count"), hit.view_count),
                    comment_count=_prefer_value(info.get("comment_count"), hit.comment_count),
                    upload_date=info.get("upload_date") or hit.upload_date,
                    live_status=info.get("live_status") or hit.live_status,
                    description=info.get("description") or hit.description,
                    channel_country=(
                        info.get("channel_country") or hit.channel_country
                    ),
                )
            except DownloadError as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                delay = self.retry_base_seconds * (2**attempt) + random.uniform(0, 1)
                time.sleep(delay)

        raise SearchExecutionError(
            f"Fallo el enriquecimiento de {hit.video_id}: {last_error}"
        )

    @staticmethod
    def _to_hits(info: dict[str, Any] | None) -> list[SearchHit]:
        if not info:
            return []

        hits: list[SearchHit] = []
        seen: set[str] = set()
        for entry in info.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            video_id = entry.get("id")
            if not isinstance(video_id, str) or len(video_id) != 11 or video_id in seen:
                continue
            seen.add(video_id)
            hits.append(
                SearchHit(
                    video_id=video_id,
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    title=entry.get("title") or "Sin titulo",
                    channel=entry.get("channel") or entry.get("uploader"),
                    channel_id=entry.get("channel_id") or entry.get("uploader_id"),
                    duration=entry.get("duration"),
                    view_count=entry.get("view_count"),
                    comment_count=entry.get("comment_count"),
                    upload_date=entry.get("upload_date"),
                    live_status=entry.get("live_status"),
                    description=entry.get("description"),
                    channel_country=entry.get("channel_country"),
                )
            )
        return hits


def _prefer_value(primary: Any, fallback: Any) -> Any:
    return fallback if primary is None else primary
