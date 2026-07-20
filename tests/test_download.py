from __future__ import annotations

import asyncio
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from discovery.download import (
    DownloadResult,
    VideoRequest,
    build_direct_video_requests,
    download_comments,
    download_videos,
    load_video_requests,
)
from discovery.youtube_api import YouTubeComment, YouTubeVideoMetadata


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

    def test_comment_download_writes_one_csv_per_video_with_likes_and_metadata(self) -> None:
        requests = [
            VideoRequest(
                video_id="abc123def45",
                url="https://www.youtube.com/watch?v=abc123def45",
                row_number=2,
                institution="Universidad Nacional A",
                source_title="Titulo del Excel",
                source_date="2026-07-20",
            )
        ]

        class FakeYouTubeClient:
            def fetch_video_metadata(
                self, video_ids: list[str]
            ) -> dict[str, YouTubeVideoMetadata]:
                return {
                    video_ids[0]: YouTubeVideoMetadata(
                        comment_count=1,
                        upload_date="20240419",
                        title="Titulo de YouTube",
                        channel_title="Canal de prueba",
                    )
                }

            def fetch_comments(
                self,
                _video_id: str,
                *,
                include_replies: bool,
                max_comments: int | None,
            ) -> list[YouTubeComment]:
                self.options = (include_replies, max_comments)
                return [
                    YouTubeComment(
                        comment_id="comment-1",
                        parent_comment_id=None,
                        is_reply=False,
                        author_display_name="Estudiante",
                        author_channel_id="UC-student",
                        text="Buena experiencia",
                        like_count=12,
                        published_at="2025-05-01T10:00:00Z",
                        updated_at="2025-05-01T10:00:00Z",
                        reply_count=0,
                    )
                ]

        client = FakeYouTubeClient()
        with tempfile.TemporaryDirectory() as temp_dir:
            download_root = Path(temp_dir) / "downloads"
            results = asyncio.run(
                download_comments(
                    requests,
                    download_root=download_root,
                    youtube_client=client,  # type: ignore[arg-type]
                    workers=1,
                )
            )
            csv_path = (
                download_root
                / "universidad_nacional_a"
                / "comments"
                / "abc123def45_comments.csv"
            )
            with csv_path.open(encoding="utf-8-sig", newline="") as source:
                rows = list(csv.DictReader(source))

        self.assertEqual("completed", results[0].status)
        self.assertEqual(1, results[0].comment_count)
        self.assertEqual("Titulo de YouTube", rows[0]["video_title"])
        self.assertEqual("20240419", rows[0]["video_upload_date"])
        self.assertEqual("12", rows[0]["like_count"])
        self.assertEqual("Buena experiencia", rows[0]["comment_text"])

