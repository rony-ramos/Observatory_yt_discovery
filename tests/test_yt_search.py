from __future__ import annotations

import unittest
from unittest.mock import patch

from discovery.yt_search import SearchHit, YtDlpSearcher


class YtDlpCookieTests(unittest.TestCase):
    def test_browser_cookies_are_passed_to_search_and_metadata(self) -> None:
        options_seen: list[dict[str, object]] = []

        class FakeDownloadError(Exception):
            pass

        class FakeYoutubeDL:
            def __init__(self, options: dict[str, object]) -> None:
                options_seen.append(options)

            def __enter__(self) -> "FakeYoutubeDL":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def extract_info(self, target: str, *, download: bool) -> dict[str, object]:
                if target.startswith("ytsearch"):
                    return {"entries": [{"id": "abc123def45", "title": "Video"}]}
                return {"id": "abc123def45", "title": "Video", "duration": 120}

        searcher = YtDlpSearcher(
            retries=0,
            cookies_from_browser="chrome",
            cookies_browser_profile="Default",
        )
        with patch.object(
            YtDlpSearcher,
            "_dependencies",
            return_value=(FakeYoutubeDL, FakeDownloadError),
        ):
            hits = searcher.search("consulta", 1)
            searcher.enrich(
                SearchHit(
                    video_id=hits[0].video_id,
                    url=hits[0].url,
                    title=hits[0].title,
                    channel=None,
                    channel_id=None,
                    duration=None,
                    view_count=None,
                    comment_count=None,
                    upload_date=None,
                    live_status=None,
                )
            )

        self.assertEqual(len(options_seen), 2)
        self.assertEqual(
            options_seen[0]["cookiesfrombrowser"],
            ("chrome", "Default", None, None),
        )
        self.assertEqual(
            options_seen[1]["cookiesfrombrowser"],
            ("chrome", "Default", None, None),
        )

