from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


class YouTubeApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class YouTubeVideoMetadata:
    comment_count: int | None = None
    upload_date: str | None = None


class YouTubeVideoApiClient:
    ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
    BATCH_SIZE = 50

    def __init__(self, api_key: str, *, timeout: float = 30.0) -> None:
        if not api_key:
            raise ValueError("api_key no puede estar vacio.")
        self.api_key = api_key
        self.timeout = timeout

    def fetch_comment_counts(self, video_ids: list[str]) -> dict[str, int | None]:
        return {
            video_id: metadata.comment_count
            for video_id, metadata in self.fetch_video_metadata(video_ids).items()
        }

    def fetch_video_metadata(
        self, video_ids: list[str]
    ) -> dict[str, YouTubeVideoMetadata]:
        metadata: dict[str, YouTubeVideoMetadata] = {}
        for start in range(0, len(video_ids), self.BATCH_SIZE):
            batch = video_ids[start : start + self.BATCH_SIZE]
            metadata.update(self._fetch_video_metadata_batch(batch))
        return metadata

    def _fetch_video_metadata_batch(
        self, video_ids: list[str]
    ) -> dict[str, YouTubeVideoMetadata]:
        if not video_ids:
            return {}

        query = urlencode(
            {
                "part": "snippet,statistics",
                "id": ",".join(video_ids),
                "key": self.api_key,
                "fields": "items(id,snippet/publishedAt,statistics/commentCount)",
            }
        )
        request_url = f"{self.ENDPOINT}?{query}"
        try:
            with urlopen(request_url, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise YouTubeApiError(f"YouTube API HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise YouTubeApiError(f"No se pudo consultar YouTube API: {exc}") from exc

        metadata = {
            video_id: YouTubeVideoMetadata()
            for video_id in video_ids
        }
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            video_id = item.get("id")
            if not isinstance(video_id, str):
                continue
            comment_count = (item.get("statistics") or {}).get("commentCount")
            published_at = (item.get("snippet") or {}).get("publishedAt")
            try:
                parsed_comment_count = int(comment_count)
            except (TypeError, ValueError):
                parsed_comment_count = None
            metadata[video_id] = YouTubeVideoMetadata(
                comment_count=parsed_comment_count,
                upload_date=_to_upload_date(published_at),
            )
        return metadata


def _to_upload_date(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.strftime("%Y%m%d")
