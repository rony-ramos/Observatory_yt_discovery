from __future__ import annotations

import json
import unittest
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
