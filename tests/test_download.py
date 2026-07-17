from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from discovery.download import (
    DownloadResult,
    VideoRequest,
    build_direct_video_requests,
    download_videos,
    load_video_requests,
)


class VideoDownloadTests(unittest.TestCase):
    def test_direct_requests_accept_ids_and_urls_without_duplicates(self) -> None:
        requests = build_direct_video_requests(
            ["abc123def45", "https://youtu.be/abc123def45"],
            "Universidad Nacional A",
        )

        self.assertEqual(1, len(requests))
        self.assertEqual("abc123def45", requests[0].video_id)
        self.assertEqual("Universidad Nacional A", requests[0].institution)

    def test_load_requests_uses_institution_and_deduplicates_within_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "videos.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["Institucion", "Video_id", "url"])
            sheet.append(["Universidad A", "abc123def45", None])
            sheet.append(["Universidad A", "abc123def45", None])
            sheet.append(["Universidad B", "abc123def45", None])
            workbook.save(input_path)
            workbook.close()

            requests = load_video_requests(input_path)

        self.assertEqual(2, len(requests))
        self.assertEqual(["Universidad A", "Universidad B"], [item.institution for item in requests])

    def test_async_downloads_receive_a_directory_per_institution(self) -> None:
        requests = [
            VideoRequest(
                video_id="abc123def45",
                url="https://www.youtube.com/watch?v=abc123def45",
                row_number=2,
                institution="Universidad Nacional A",
            ),
            VideoRequest(
                video_id="xyz987uvw65",
                url="https://www.youtube.com/watch?v=xyz987uvw65",
                row_number=3,
                institution="Universidad Nacional B",
            ),
        ]

        def fake_download(
            request: VideoRequest,
            *,
            download_root: Path,
            **_kwargs: object,
        ) -> DownloadResult:
            folder = download_root / request.institution.lower().replace(" ", "_")
            folder.mkdir(parents=True, exist_ok=True)
            file_path = folder / f"{request.video_id}.mp4"
            file_path.write_text("video", encoding="utf-8")
            return DownloadResult(
                video_id=request.video_id,
                url=request.url,
                row_number=request.row_number,
                institution=request.institution,
                status="completed",
                file_path=str(file_path),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            download_root = Path(temp_dir) / "downloads"
            with patch("discovery.download._download_one", side_effect=fake_download):
                results = asyncio.run(download_videos(requests, download_root=download_root, workers=2))

            self.assertEqual(2, len(results))
            self.assertTrue(
                (download_root / "universidad_nacional_a" / "abc123def45.mp4").is_file()
            )
            self.assertTrue(
                (download_root / "universidad_nacional_b" / "xyz987uvw65.mp4").is_file()
            )

