from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from discovery.youtube_api import YouTubeVideoApiClient


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class YouTubeApiTests(unittest.TestCase):
    def test_fetch_video_metadata_includes_title_channel_and_date(self) -> None:
        payload = {
            "items": [
                {
                    "id": "abc123def45",
                    "snippet": {
                        "publishedAt": "2024-04-19T13:15:00Z",
                        "title": "Vida universitaria",
                        "channelTitle": "Canal Estudiantil",
                    },
                    "statistics": {"commentCount": "81"},
                }
            ]
        }
        client = YouTubeVideoApiClient("test-key")

        with patch(
            "discovery.youtube_api.urlopen", return_value=FakeResponse(payload)
        ):
            metadata = client.fetch_video_metadata(["abc123def45"])["abc123def45"]

        self.assertEqual("Vida universitaria", metadata.title)
        self.assertEqual("Canal Estudiantil", metadata.channel_title)
        self.assertEqual("20240419", metadata.upload_date)
        self.assertEqual(81, metadata.comment_count)

    def test_fetch_comments_downloads_all_replies_and_likes(self) -> None:
        thread_payload = {
            "items": [
                {
                    "snippet": {
                        "totalReplyCount": 2,
                        "topLevelComment": {
                            "id": "top-1",
                            "snippet": {
                                "authorDisplayName": "Ana",
                                "authorChannelId": {"value": "UC-ana"},
                                "textDisplay": "Buen video",
                                "likeCount": 7,
                                "publishedAt": "2025-01-02T10:00:00Z",
                                "updatedAt": "2025-01-02T10:00:00Z",
                            },
                        },
                    },
                    "replies": {"comments": [{"id": "partial"}]},
                }
            ]
        }
        replies_payload = {
            "items": [
                {
                    "id": "reply-1",
                    "snippet": {
                        "parentId": "top-1",
                        "authorDisplayName": "Luis",
                        "textDisplay": "Gracias",
                        "likeCount": 3,
                        "publishedAt": "2025-01-03T10:00:00Z",
                        "updatedAt": "2025-01-03T10:00:00Z",
                    },
                },
                {
                    "id": "reply-2",
                    "snippet": {
                        "parentId": "top-1",
                        "authorDisplayName": "Maria",
                        "textDisplay": "De acuerdo",
                        "likeCount": 1,
                    },
                },
            ]
        }
        client = YouTubeVideoApiClient("test-key")

        def fake_urlopen(url: str, **_kwargs: object) -> FakeResponse:
            query = parse_qs(urlparse(url).query)
            if "videoId" in query:
                return FakeResponse(thread_payload)
            return FakeResponse(replies_payload)

        with patch("discovery.youtube_api.urlopen", side_effect=fake_urlopen):
            comments = client.fetch_comments("abc123def45")

        self.assertEqual(["top-1", "reply-1", "reply-2"], [c.comment_id for c in comments])
        self.assertEqual([7, 3, 1], [c.like_count for c in comments])
        self.assertEqual(2, comments[0].reply_count)
        self.assertTrue(comments[1].is_reply)
        self.assertEqual("top-1", comments[1].parent_comment_id)

    def test_fetch_channel_countries_preserves_unknown_values(self) -> None:
        payload = {
            "items": [
                {"id": "UC-ar", "snippet": {"country": "AR"}},
                {"id": "UC-br", "snippet": {"country": "br"}},
                {"id": "UC-unknown", "snippet": {}},
            ]
        }
        client = YouTubeVideoApiClient("test-key")

        with patch(
            "discovery.youtube_api.urlopen",
            return_value=FakeResponse(payload),
        ) as mocked_urlopen:
            countries = client.fetch_channel_countries(
                ["UC-ar", "UC-br", "UC-unknown"]
            )

        request_url = mocked_urlopen.call_args.args[0]
        self.assertIn("/youtube/v3/channels?", request_url)
        self.assertEqual(
            {"UC-ar": "AR", "UC-br": "BR", "UC-unknown": None},
            countries,
        )


if __name__ == "__main__":
    unittest.main()
