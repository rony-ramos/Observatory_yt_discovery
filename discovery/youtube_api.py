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
    title: str | None = None
    channel_title: str | None = None


@dataclass(frozen=True)
class YouTubeComment:
    comment_id: str
    parent_comment_id: str | None
    is_reply: bool
    author_display_name: str | None
    author_channel_id: str | None
    text: str
    like_count: int
    published_at: str | None
    updated_at: str | None
    reply_count: int | None = None


class YouTubeVideoApiClient:
    VIDEO_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
    CHANNEL_ENDPOINT = "https://www.googleapis.com/youtube/v3/channels"
    COMMENT_THREADS_ENDPOINT = "https://www.googleapis.com/youtube/v3/commentThreads"
    COMMENTS_ENDPOINT = "https://www.googleapis.com/youtube/v3/comments"
    ENDPOINT = VIDEO_ENDPOINT
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
                "fields": (
                    "items(id,snippet(publishedAt,title,channelTitle),"
                    "statistics/commentCount)"
                ),
            }
        )
        request_url = f"{self.VIDEO_ENDPOINT}?{query}"
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
            snippet = item.get("snippet") or {}
            published_at = snippet.get("publishedAt")
            try:
                parsed_comment_count = int(comment_count)
            except (TypeError, ValueError):
                parsed_comment_count = None
            metadata[video_id] = YouTubeVideoMetadata(
                comment_count=parsed_comment_count,
                upload_date=_to_upload_date(published_at),
                title=_optional_text(snippet.get("title")),
                channel_title=_optional_text(snippet.get("channelTitle")),
            )
        return metadata

    def fetch_comments(
        self,
        video_id: str,
        *,
        include_replies: bool = True,
        max_comments: int | None = None,
    ) -> list[YouTubeComment]:
        if not video_id:
            raise ValueError("video_id no puede estar vacio.")
        if max_comments is not None and max_comments < 1:
            raise ValueError("max_comments debe ser mayor que cero.")

        comments: list[YouTubeComment] = []
        page_token: str | None = None
        while True:
            params = {
                "part": "snippet,replies",
                "videoId": video_id,
                "maxResults": "100",
                "order": "time",
                "textFormat": "plainText",
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._request_json(self.COMMENT_THREADS_ENDPOINT, params)

            for thread in payload.get("items") or []:
                if not isinstance(thread, dict):
                    continue
                thread_snippet = thread.get("snippet") or {}
                if not isinstance(thread_snippet, dict):
                    continue
                top_level = thread_snippet.get("topLevelComment")
                if not isinstance(top_level, dict):
                    continue
                total_replies = _to_int(thread_snippet.get("totalReplyCount"), default=0)
                comments.append(
                    _parse_comment_resource(top_level, reply_count=total_replies)
                )
                if _limit_reached(comments, max_comments):
                    return comments[:max_comments]

                if include_replies and total_replies:
                    inline_replies = (thread.get("replies") or {}).get("comments") or []
                    if len(inline_replies) >= total_replies:
                        replies = inline_replies
                    else:
                        replies = self._fetch_replies(top_level.get("id", ""))
                    for reply in replies:
                        if not isinstance(reply, dict):
                            continue
                        comments.append(_parse_comment_resource(reply))
                        if _limit_reached(comments, max_comments):
                            return comments[:max_comments]

            page_token = _optional_text(payload.get("nextPageToken"))
            if not page_token:
                return comments

    def _fetch_replies(self, parent_id: str) -> list[dict[str, object]]:
        if not parent_id:
            return []
        replies: list[dict[str, object]] = []
        page_token: str | None = None
        while True:
            params = {
                "part": "snippet",
                "parentId": parent_id,
                "maxResults": "100",
                "textFormat": "plainText",
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self._request_json(self.COMMENTS_ENDPOINT, params)
            replies.extend(
                item for item in (payload.get("items") or []) if isinstance(item, dict)
            )
            page_token = _optional_text(payload.get("nextPageToken"))
            if not page_token:
                return replies

    def _request_json(
        self, endpoint: str, params: dict[str, str]
    ) -> dict[str, object]:
        query = urlencode({**params, "key": self.api_key})
        request_url = f"{endpoint}?{query}"
        try:
            with urlopen(request_url, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise YouTubeApiError(f"YouTube API HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise YouTubeApiError(f"No se pudo consultar YouTube API: {exc}") from exc
        if not isinstance(payload, dict):
            raise YouTubeApiError("YouTube API devolvio una respuesta inesperada.")
        return payload

    def fetch_channel_countries(
        self, channel_ids: list[str]
    ) -> dict[str, str | None]:
        countries: dict[str, str | None] = {}
        unique_ids = list(dict.fromkeys(channel_ids))
        for start in range(0, len(unique_ids), self.BATCH_SIZE):
            batch = unique_ids[start : start + self.BATCH_SIZE]
            countries.update(self._fetch_channel_countries_batch(batch))
        return countries

    def _fetch_channel_countries_batch(
        self, channel_ids: list[str]
    ) -> dict[str, str | None]:
        if not channel_ids:
            return {}

        query = urlencode(
            {
                "part": "snippet",
                "id": ",".join(channel_ids),
                "key": self.api_key,
                "fields": "items(id,snippet/country)",
            }
        )
        request_url = f"{self.CHANNEL_ENDPOINT}?{query}"
        try:
            with urlopen(request_url, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise YouTubeApiError(f"YouTube API HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise YouTubeApiError(f"No se pudo consultar YouTube API: {exc}") from exc

        countries = {channel_id: None for channel_id in channel_ids}
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            channel_id = item.get("id")
            country = (item.get("snippet") or {}).get("country")
            if not isinstance(channel_id, str):
                continue
            countries[channel_id] = (
                country.upper() if isinstance(country, str) and country else None
            )
        return countries


def _to_upload_date(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.strftime("%Y%m%d")


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _to_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _limit_reached(
    comments: list[YouTubeComment], max_comments: int | None
) -> bool:
    return max_comments is not None and len(comments) >= max_comments


def _parse_comment_resource(
    resource: dict[str, object], *, reply_count: int | None = None
) -> YouTubeComment:
    snippet = resource.get("snippet") or {}
    if not isinstance(snippet, dict):
        snippet = {}
    author_channel = snippet.get("authorChannelId") or {}
    author_channel_id = (
        author_channel.get("value") if isinstance(author_channel, dict) else None
    )
    parent_id = _optional_text(snippet.get("parentId"))
    return YouTubeComment(
        comment_id=str(resource.get("id") or ""),
        parent_comment_id=parent_id,
        is_reply=parent_id is not None,
        author_display_name=_optional_text(snippet.get("authorDisplayName")),
        author_channel_id=_optional_text(author_channel_id),
        text=str(snippet.get("textDisplay") or snippet.get("textOriginal") or ""),
        like_count=_to_int(snippet.get("likeCount")),
        published_at=_optional_text(snippet.get("publishedAt")),
        updated_at=_optional_text(snippet.get("updatedAt")),
        reply_count=reply_count,
    )
