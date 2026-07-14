from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


class YouTubeApiError(RuntimeError):
    pass


class YouTubeVideoApiClient:
    ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
    BATCH_SIZE = 50

    def __init__(self, api_key: str, *, timeout: float = 30.0) -> None:
        if not api_key:
            raise ValueError("api_key no puede estar vacio.")
        self.api_key = api_key
        self.timeout = timeout

    def fetch_comment_counts(self, video_ids: list[str]) -> dict[str, int | None]:
        counts: dict[str, int | None] = {}
        for start in range(0, len(video_ids), self.BATCH_SIZE):
            batch = video_ids[start : start + self.BATCH_SIZE]
            counts.update(self._fetch_comment_count_batch(batch))
        return counts

    def _fetch_comment_count_batch(self, video_ids: list[str]) -> dict[str, int | None]:
        if not video_ids:
            return {}

        query = urlencode(
            {
                "part": "statistics",
                "id": ",".join(video_ids),
                "key": self.api_key,
                "fields": "items(id,statistics/commentCount)",
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

        counts = {video_id: None for video_id in video_ids}
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            video_id = item.get("id")
            if not isinstance(video_id, str):
                continue
            comment_count = (item.get("statistics") or {}).get("commentCount")
            try:
                counts[video_id] = int(comment_count)
            except (TypeError, ValueError):
                counts[video_id] = None
        return counts
