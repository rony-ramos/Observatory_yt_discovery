from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from discovery.dictionary import KeywordDictionary
from discovery.institutions import InstitutionRegistry
from discovery.pipeline import run_search_pipeline
from discovery.planner import plan_queries
from discovery.youtube_api import YouTubeVideoMetadata
from discovery.yt_search import SearchExecutionError, SearchHit


class FakeSearcher:
    def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [
            SearchHit(
                video_id="abc123def45",
                url="https://www.youtube.com/watch?v=abc123def45",
                title=f"Resultado para {query}",
                channel="Canal de prueba",
                channel_id="UC-test",
                duration=600,
                view_count=1000,
                comment_count=None,
                upload_date=None,
                live_status=None,
            )
        ][:max_results]

    def enrich(self, hit: SearchHit) -> SearchHit:
        return hit


class DatePreferenceSearcher:
    def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [
            SearchHit(
                video_id="new123def45",
                url="https://www.youtube.com/watch?v=new123def45",
                title="UBA video reciente",
                channel="Canal",
                channel_id="UC-new",
                duration=None,
                view_count=None,
                comment_count=None,
                upload_date=None,
                live_status=None,
            ),
            SearchHit(
                video_id="old123def45",
                url="https://www.youtube.com/watch?v=old123def45",
                title="UBA video antiguo",
                channel="Canal",
                channel_id="UC-old",
                duration=None,
                view_count=None,
                comment_count=None,
                upload_date=None,
                live_status=None,
            ),
        ][:max_results]

    def enrich(self, hit: SearchHit) -> SearchHit:
        upload_date = "20230315" if hit.video_id.startswith("new") else "20200115"
        return replace(hit, upload_date=upload_date, duration=300)


class InstitutionFilterSearcher:
    def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [
            SearchHit(
                video_id="uba123def45",
                url="https://www.youtube.com/watch?v=uba123def45",
                title="Curso de ingreso a la UBA",
                channel="Canal estudiantil",
                channel_id="UC-uba",
                duration=300,
                view_count=100,
                comment_count=10,
                upload_date="20240101",
                live_status=None,
                description="Universidad de Buenos Aires",
            ),
            SearchHit(
                video_id="utn123def45",
                url="https://www.youtube.com/watch?v=utn123def45",
                title="Curso de ingreso a la UTN",
                channel="Canal estudiantil",
                channel_id="UC-utn",
                duration=300,
                view_count=100,
                comment_count=10,
                upload_date="20240101",
                live_status=None,
                description="Universidad Tecnologica Nacional",
            ),
        ][:max_results]

    def enrich(self, hit: SearchHit) -> SearchHit:
        return hit


class CompactAliasSearcher:
    def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [
            SearchHit(
                video_id="unam12def45",
                url="https://www.youtube.com/watch?v=unam12def45",
                title="Acreditacion de Contaduria y Administracion 2025",
                channel="FESCUNAMoficial",
                channel_id="UC-unam",
                duration=300,
                view_count=100,
                comment_count=10,
                upload_date="20250101",
                live_status=None,
            )
        ][:max_results]

    def enrich(self, hit: SearchHit) -> SearchHit:
        return hit


class UnavailableMetadataSearcher:
    def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [
            SearchHit(
                video_id="dead12def45",
                url="https://www.youtube.com/watch?v=dead12def45",
                title="Video sobre la USIL",
                channel="Canal estudiantil",
                channel_id="UC-dead",
                duration=300,
                view_count=100,
                comment_count=10,
                upload_date=None,
                live_status=None,
            )
        ][:max_results]

    def enrich(self, hit: SearchHit) -> SearchHit:
        raise SearchExecutionError(
            "[youtube] dead12def45: This video is not available"
        )


class CountingUnavailableMetadataSearcher(UnavailableMetadataSearcher):
    def __init__(self) -> None:
        self.enrich_calls = 0

    def enrich(self, hit: SearchHit) -> SearchHit:
        self.enrich_calls += 1
        return super().enrich(hit)


class OfficialChannelSearcher:
    def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [
            SearchHit(
                video_id="off123def45",
                url="https://www.youtube.com/watch?v=off123def45",
                title="Vida de estudiante USIL",
                channel="USIL I Universidad San Ignacio de Loyola",
                channel_id="UC-official",
                duration=300,
                view_count=100,
                comment_count=10,
                upload_date="20240101",
                live_status=None,
            ),
            SearchHit(
                video_id="stu123def45",
                url="https://www.youtube.com/watch?v=stu123def45",
                title="Mi primer dia en la USIL",
                channel="Canal estudiantil",
                channel_id="UC-student",
                duration=300,
                view_count=100,
                comment_count=10,
                upload_date="20240101",
                live_status=None,
            ),
        ][:max_results]

    def enrich(self, hit: SearchHit) -> SearchHit:
        return hit


class CommentCountSearcher:
    def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [
            SearchHit(
                video_id="high12def45",
                url="https://www.youtube.com/watch?v=high12def45",
                title="Curso de ingreso a la UBA",
                channel="Canal estudiantil",
                channel_id="UC-high",
                duration=300,
                view_count=100,
                comment_count=80,
                upload_date="20240101",
                live_status=None,
                description="Universidad de Buenos Aires",
            ),
            SearchHit(
                video_id="low123def45",
                url="https://www.youtube.com/watch?v=low123def45",
                title="CBC UBA experiencia",
                channel="Canal estudiantil",
                channel_id="UC-low",
                duration=300,
                view_count=100,
                comment_count=74,
                upload_date="20240101",
                live_status=None,
                description="Universidad de Buenos Aires",
            ),
            SearchHit(
                video_id="miss12def45",
                url="https://www.youtube.com/watch?v=miss12def45",
                title="Ingreso UBA preguntas",
                channel="Canal estudiantil",
                channel_id="UC-miss",
                duration=300,
                view_count=100,
                comment_count=None,
                upload_date="20240101",
                live_status=None,
                description="Universidad de Buenos Aires",
            ),
        ][:max_results]

    def enrich(self, hit: SearchHit) -> SearchHit:
        return hit


class UploadDateApiFallbackSearcher:
    def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [
            SearchHit(
                video_id="date12def45",
                url="https://www.youtube.com/watch?v=date12def45",
                title="Curso de ingreso a la UBA",
                channel="Canal estudiantil",
                channel_id="UC-date",
                duration=300,
                view_count=100,
                comment_count=80,
                upload_date=None,
                live_status=None,
                description="Universidad de Buenos Aires",
            )
        ][:max_results]

    def enrich(self, hit: SearchHit) -> SearchHit:
        return hit


class SourceCountrySearcher:
    def search(self, query: str, max_results: int) -> list[SearchHit]:
        return [
            SearchHit(
                video_id="arg123def45",
                url="https://www.youtube.com/watch?v=arg123def45",
                title="Experiencia estudiando en la UBA",
                channel="Estudiante argentino",
                channel_id="UC-ar",
                duration=300,
                view_count=1000,
                comment_count=100,
                upload_date="20240101",
                live_status=None,
                description="Universidad de Buenos Aires",
            ),
            SearchHit(
                video_id="bra123def45",
                url="https://www.youtube.com/watch?v=bra123def45",
                title="Como estudar na UBA",
                channel="Estudante brasileiro",
                channel_id="UC-br",
                duration=300,
                view_count=1000,
                comment_count=100,
                upload_date="20240101",
                live_status=None,
                description="Universidad de Buenos Aires",
            ),
            SearchHit(
                video_id="unk123def45",
                url="https://www.youtube.com/watch?v=unk123def45",
                title="Mi experiencia en la UBA",
                channel="Canal sin pais",
                channel_id="UC-unknown",
                duration=300,
                view_count=1000,
                comment_count=100,
                upload_date="20240101",
                live_status=None,
                description="Universidad de Buenos Aires",
            ),
        ][:max_results]

    def enrich(self, hit: SearchHit) -> SearchHit:
        return hit


class FakeCommentApiClient:
    def __init__(
        self,
        counts: dict[str, int | None],
        upload_dates: dict[str, str | None] | None = None,
        channel_countries: dict[str, str | None] | None = None,
    ) -> None:
        self.counts = counts
        self.upload_dates = upload_dates or {}
        self.channel_countries = channel_countries or {}
        self.calls: list[list[str]] = []
        self.channel_calls: list[list[str]] = []

    def fetch_comment_counts(self, video_ids: list[str]) -> dict[str, int | None]:
        return {
            video_id: metadata.comment_count
            for video_id, metadata in self.fetch_video_metadata(video_ids).items()
        }

    def fetch_video_metadata(
        self, video_ids: list[str]
    ) -> dict[str, YouTubeVideoMetadata]:
        self.calls.append(video_ids)
        return {
            video_id: YouTubeVideoMetadata(
                comment_count=self.counts.get(video_id),
                upload_date=self.upload_dates.get(video_id),
            )
            for video_id in video_ids
        }

    def fetch_channel_countries(
        self, channel_ids: list[str]
    ) -> dict[str, str | None]:
        self.channel_calls.append(channel_ids)
        return {
            channel_id: self.channel_countries.get(channel_id)
            for channel_id in channel_ids
        }


class QueryPlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dictionary = KeywordDictionary.load()

    def test_plan_is_balanced_and_deduplicated(self) -> None:
        queries = plan_queries(
            self.dictionary,
            institution="Universidad de Buenos Aires",
            aliases=["UBA"],
            country="AR",
            indicators=["ingreso"],
            max_queries=12,
            variants_per_term=2,
        )

        self.assertEqual(12, len(queries))
        self.assertEqual({"matricula", "admision"}, {item.concept for item in queries})
        self.assertEqual(len(queries), len({item.query.casefold() for item in queries}))
        self.assertTrue(any(item.locale == "AR" for item in queries))

    def test_invalid_concept_indicator_pair_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            plan_queries(
                self.dictionary,
                institution="Universidad de Buenos Aires",
                aliases=["UBA"],
                country="AR",
                indicators=["ingreso"],
                concepts=["costo"],
            )

    def test_dry_run_writes_reproducible_plan(self) -> None:
        queries = plan_queries(
            self.dictionary,
            institution="Universidad de Buenos Aires",
            aliases=["UBA"],
            country="AR",
            indicators=["ingreso"],
            max_queries=4,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = run_search_pipeline(
                queries=queries,
                institution="Universidad de Buenos Aires",
                aliases=["UBA"],
                country="AR",
                results_per_query=10,
                output_root=Path(temporary_directory),
                dry_run=True,
            )

            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            with (run_dir / "queries.csv").open(encoding="utf-8-sig", newline="") as source:
                rows = list(csv.DictReader(source))

            self.assertEqual("planned", manifest["status"])
            self.assertEqual(self.dictionary.version, manifest["dictionary_version"])
            self.assertEqual(4, len(rows))

    def test_execution_deduplicates_videos_and_preserves_queries(self) -> None:
        queries = plan_queries(
            self.dictionary,
            institution="Universidad de Buenos Aires",
            aliases=["UBA"],
            country="AR",
            indicators=["ingreso"],
            max_queries=2,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = run_search_pipeline(
                queries=queries,
                institution="Universidad de Buenos Aires",
                aliases=["UBA"],
                country="AR",
                results_per_query=1,
                output_root=Path(temporary_directory),
                searcher=FakeSearcher(),
                min_sleep=0,
                max_sleep=0,
                min_comments=0,
                sleep=lambda _: None,
            )

            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            with (run_dir / "videos.csv").open(encoding="utf-8-sig", newline="") as source:
                videos = list(csv.DictReader(source))
            raw_lines = (run_dir / "results_raw.jsonl").read_text(encoding="utf-8").splitlines()

            self.assertEqual("completed", manifest["status"])
            self.assertEqual(2, manifest["raw_results"])
            self.assertEqual(1, manifest["unique_videos"])
            self.assertEqual(2, len(raw_lines))
            self.assertEqual("2", videos[0]["occurrences"])
            self.assertEqual("q0001;q0002", videos[0]["query_ids"])

    def test_video_report_preserves_search_indicators_queries_and_keywords(self) -> None:
        queries = plan_queries(
            self.dictionary,
            institution="Universidad de Buenos Aires",
            aliases=["UBA"],
            country="AR",
            indicators=["ingreso", "dinero"],
            max_queries=2,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = run_search_pipeline(
                queries=queries,
                institution="Universidad de Buenos Aires",
                aliases=["UBA"],
                country="AR",
                results_per_query=1,
                output_root=Path(temporary_directory),
                searcher=FakeSearcher(),
                min_sleep=0,
                max_sleep=0,
                min_comments=0,
                sleep=lambda _: None,
            )

            with (run_dir / "videos.csv").open(encoding="utf-8-sig", newline="") as source:
                videos = list(csv.DictReader(source))

            expected_queries = ";".join(sorted(query.query for query in queries))
            expected_keywords = ";".join(sorted(query.term for query in queries))
            expected_indicators = ";".join(sorted({query.indicator for query in queries}))

            self.assertEqual(expected_indicators, videos[0]["indicators"])
            self.assertEqual(expected_queries, videos[0]["search_queries"])
            self.assertEqual(expected_keywords, videos[0]["keywords"])

    def test_date_preference_enriches_and_orders_recent_videos_first(self) -> None:
        queries = plan_queries(
            self.dictionary,
            institution="Universidad de Buenos Aires",
            aliases=["UBA"],
            country="AR",
            indicators=["ingreso"],
            max_queries=1,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = run_search_pipeline(
                queries=queries,
                institution="Universidad de Buenos Aires",
                aliases=["UBA"],
                country="AR",
                results_per_query=2,
                output_root=Path(temporary_directory),
                searcher=DatePreferenceSearcher(),
                min_sleep=0,
                max_sleep=0,
                published_after=date(2021, 12, 31),
                date_policy="prefer",
                metadata_min_sleep=0,
                metadata_max_sleep=0,
                min_comments=0,
                sleep=lambda _: None,
            )

            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            with (run_dir / "videos.csv").open(encoding="utf-8-sig", newline="") as source:
                videos = list(csv.DictReader(source))

            self.assertEqual(2, manifest["metadata_enriched"])
            self.assertEqual(1, manifest["date_preferred"])
            self.assertEqual(1, manifest["date_older"])
            self.assertEqual("new123def45", videos[0]["video_id"])
            self.assertEqual("True", videos[0]["published_after_match"])
            self.assertEqual("False", videos[1]["published_after_match"])

    def test_strict_institution_policy_separates_false_positives(self) -> None:
        queries = plan_queries(
            self.dictionary,
            institution="Universidad de Buenos Aires",
            aliases=["UBA"],
            country="AR",
            indicators=["ingreso"],
            max_queries=1,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = run_search_pipeline(
                queries=queries,
                institution="Universidad de Buenos Aires",
                aliases=["UBA"],
                country="AR",
                results_per_query=2,
                output_root=Path(temporary_directory),
                searcher=InstitutionFilterSearcher(),
                min_sleep=0,
                max_sleep=0,
                published_after=date(2021, 12, 31),
                institution_policy="strict",
                min_comments=0,
                sleep=lambda _: None,
            )

            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            with (run_dir / "videos.csv").open(encoding="utf-8-sig", newline="") as source:
                selected = list(csv.DictReader(source))
            with (run_dir / "rejected.csv").open(encoding="utf-8-sig", newline="") as source:
                rejected = list(csv.DictReader(source))

            self.assertEqual(1, manifest["institution_matched"])
            self.assertEqual(1, manifest["institution_rejected"])
            self.assertEqual("uba123def45", selected[0]["video_id"])
            self.assertEqual("utn123def45", rejected[0]["video_id"])

    def test_compact_alias_matches_channel_names(self) -> None:
        queries = plan_queries(
            self.dictionary,
            institution="Universidad Nacional Autonoma de Mexico",
            aliases=["UNAM"],
            country="MX",
            indicators=["calidad"],
            max_queries=1,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = run_search_pipeline(
                queries=queries,
                institution="Universidad Nacional Autonoma de Mexico",
                aliases=["UNAM"],
                country="MX",
                results_per_query=1,
                output_root=Path(temporary_directory),
                searcher=CompactAliasSearcher(),
                min_sleep=0,
                max_sleep=0,
                institution_policy="strict",
                min_comments=0,
                sleep=lambda _: None,
            )

            with (run_dir / "videos.csv").open(encoding="utf-8-sig", newline="") as source:
                selected = list(csv.DictReader(source))

            self.assertEqual("unam12def45", selected[0]["video_id"])
            self.assertEqual("UNAM", selected[0]["matched_aliases"])

    def test_unavailable_metadata_is_rejected(self) -> None:
        queries = plan_queries(
            self.dictionary,
            institution="Universidad San Ignacio de Loyola",
            aliases=["USIL"],
            country="PE",
            indicators=["vida_campus"],
            max_queries=1,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = run_search_pipeline(
                queries=queries,
                institution="Universidad San Ignacio de Loyola",
                aliases=["USIL"],
                country="PE",
                results_per_query=1,
                output_root=Path(temporary_directory),
                searcher=UnavailableMetadataSearcher(),
                min_sleep=0,
                max_sleep=0,
                metadata_min_sleep=0,
                metadata_max_sleep=0,
                published_after=date(2021, 12, 31),
                institution_policy="strict",
                min_comments=0,
                sleep=lambda _: None,
            )

            with (run_dir / "videos.csv").open(encoding="utf-8-sig", newline="") as source:
                selected = list(csv.DictReader(source))
            with (run_dir / "rejected.csv").open(encoding="utf-8-sig", newline="") as source:
                rejected = list(csv.DictReader(source))

            self.assertEqual([], selected)
            self.assertEqual("dead12def45", rejected[0]["video_id"])
            self.assertEqual("metadata_unavailable", rejected[0]["rejection_reason"])

    def test_min_comments_filters_and_api_fills_missing_counts(self) -> None:
        queries = plan_queries(
            self.dictionary,
            institution="Universidad de Buenos Aires",
            aliases=["UBA"],
            country="AR",
            indicators=["ingreso"],
            max_queries=1,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            api_client = FakeCommentApiClient({"miss12def45": 120})
            run_dir = run_search_pipeline(
                queries=queries,
                institution="Universidad de Buenos Aires",
                aliases=["UBA"],
                country="AR",
                results_per_query=3,
                output_root=Path(temporary_directory),
                searcher=CommentCountSearcher(),
                min_sleep=0,
                max_sleep=0,
                institution_policy="strict",
                min_comments=75,
                youtube_api_client=api_client,
                sleep=lambda _: None,
            )

            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            with (run_dir / "videos.csv").open(encoding="utf-8-sig", newline="") as source:
                selected = {
                    row["video_id"]: row["comment_count_match"]
                    for row in csv.DictReader(source)
                }
            with (run_dir / "rejected.csv").open(encoding="utf-8-sig", newline="") as source:
                rejected = {
                    row["video_id"]: row["rejection_reason"]
                    for row in csv.DictReader(source)
                }

            self.assertEqual([["miss12def45"]], api_client.calls)
            self.assertEqual(1, manifest["comment_count_api_checked"])
            self.assertEqual(1, manifest["comment_count_api_filled"])
            self.assertEqual(2, manifest["comment_count_qualified"])
            self.assertEqual({"high12def45": "True", "miss12def45": "True"}, selected)
            self.assertEqual(
                {"low123def45": "comment_count_below_minimum"},
                rejected,
            )

    def test_youtube_api_fills_missing_upload_date_for_date_filter(self) -> None:
        queries = plan_queries(
            self.dictionary,
            institution="Universidad de Buenos Aires",
            aliases=["UBA"],
            country="AR",
            indicators=["ingreso"],
            max_queries=1,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            api_client = FakeCommentApiClient(
                {},
                upload_dates={"date12def45": "20240501"},
            )
            run_dir = run_search_pipeline(
                queries=queries,
                institution="Universidad de Buenos Aires",
                aliases=["UBA"],
                country="AR",
                results_per_query=1,
                output_root=Path(temporary_directory),
                searcher=UploadDateApiFallbackSearcher(),
                min_sleep=0,
                max_sleep=0,
                published_after=date(2021, 12, 31),
                institution_policy="strict",
                min_comments=75,
                youtube_api_client=api_client,
                sleep=lambda _: None,
            )

            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            with (run_dir / "videos.csv").open(encoding="utf-8-sig", newline="") as source:
                selected = list(csv.DictReader(source))

            self.assertEqual([["date12def45"]], api_client.calls)
            self.assertEqual(1, manifest["upload_date_api_filled"])
            self.assertEqual("20240501", selected[0]["upload_date"])
            self.assertEqual("True", selected[0]["published_after_match"])

    def test_strict_source_country_rejects_foreign_and_unknown_channels(self) -> None:
        queries = plan_queries(
            self.dictionary,
            institution="Universidad de Buenos Aires",
            aliases=["UBA"],
            country="AR",
            indicators=["experiencia"],
            max_queries=1,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            api_client = FakeCommentApiClient(
                {},
                channel_countries={
                    "UC-ar": "AR",
                    "UC-br": "BR",
                    "UC-unknown": None,
                },
            )
            run_dir = run_search_pipeline(
                queries=queries,
                institution="Universidad de Buenos Aires",
                aliases=["UBA"],
                country="AR",
                results_per_query=3,
                output_root=Path(temporary_directory),
                searcher=SourceCountrySearcher(),
                min_sleep=0,
                max_sleep=0,
                institution_policy="strict",
                source_country_policy="strict",
                min_comments=0,
                youtube_api_client=api_client,
                sleep=lambda _: None,
            )

            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            with (run_dir / "videos.csv").open(
                encoding="utf-8-sig", newline=""
            ) as source:
                selected = list(csv.DictReader(source))
            with (run_dir / "rejected.csv").open(
                encoding="utf-8-sig", newline=""
            ) as source:
                rejected = {
                    row["video_id"]: row["rejection_reason"]
                    for row in csv.DictReader(source)
                }

            self.assertEqual([["UC-ar", "UC-br", "UC-unknown"]], api_client.channel_calls)
            self.assertEqual(["arg123def45"], [row["video_id"] for row in selected])
            self.assertEqual("AR", selected[0]["channel_country"])
            self.assertEqual("True", selected[0]["source_country_match"])
            self.assertEqual(
                {
                    "bra123def45": "source_country_mismatch",
                    "unk123def45": "source_country_unknown",
                },
                rejected,
            )
            self.assertEqual(1, manifest["source_country_matched"])
            self.assertEqual(1, manifest["source_country_mismatched"])
            self.assertEqual(1, manifest["source_country_unknown"])
            self.assertEqual(2, manifest["source_country_rejected"])

    def test_metadata_skip_cache_prevents_rechecking_unavailable_video(self) -> None:
        queries = plan_queries(
            self.dictionary,
            institution="Universidad San Ignacio de Loyola",
            aliases=["USIL"],
            country="PE",
            indicators=["vida_campus"],
            max_queries=1,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "metadata_skip_cache.json"
            first_searcher = CountingUnavailableMetadataSearcher()
            run_search_pipeline(
                queries=queries,
                institution="Universidad San Ignacio de Loyola",
                aliases=["USIL"],
                country="PE",
                results_per_query=1,
                output_root=Path(temporary_directory) / "run1",
                searcher=first_searcher,
                min_sleep=0,
                max_sleep=0,
                metadata_min_sleep=0,
                metadata_max_sleep=0,
                metadata_skip_cache=cache_path,
                published_after=date(2021, 12, 31),
                institution_policy="strict",
                min_comments=0,
                sleep=lambda _: None,
            )

            second_searcher = CountingUnavailableMetadataSearcher()
            run_dir = run_search_pipeline(
                queries=queries,
                institution="Universidad San Ignacio de Loyola",
                aliases=["USIL"],
                country="PE",
                results_per_query=1,
                output_root=Path(temporary_directory) / "run2",
                searcher=second_searcher,
                min_sleep=0,
                max_sleep=0,
                metadata_min_sleep=0,
                metadata_max_sleep=0,
                metadata_skip_cache=cache_path,
                published_after=date(2021, 12, 31),
                institution_policy="strict",
                min_comments=0,
                sleep=lambda _: None,
            )

            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            with (run_dir / "rejected.csv").open(encoding="utf-8-sig", newline="") as source:
                rejected = list(csv.DictReader(source))

            self.assertEqual(1, first_searcher.enrich_calls)
            self.assertEqual(0, second_searcher.enrich_calls)
            self.assertEqual(1, manifest["metadata_skipped_cached"])
            self.assertEqual("metadata_unavailable", rejected[0]["rejection_reason"])

    def test_institution_registry_allows_pending_eligibility_by_default(self) -> None:
        registry = InstitutionRegistry.load()
        pending_registry = InstitutionRegistry(
            {
                "registry": {"version": "test"},
                "institutions": [
                    {
                        "id": "pending",
                        "name": "Universidad Pendiente",
                        "country": "PE",
                        "eligibility": {
                            "national": False,
                            "licensed": True,
                            "qs_ranked": False,
                        },
                    }
                ],
            },
            Path("pending.yaml"),
        )

        self.assertEqual("uba", registry.get("uba").id)
        self.assertEqual("pending", pending_registry.get("pending").id)
        with self.assertRaises(ValueError):
            pending_registry.get("pending", require_eligible=True)
        with self.assertRaises(ValueError):
            pending_registry.get("pending", require_national=True)

    def test_institution_registry_accepts_official_channel_url_shorthand(self) -> None:
        registry = InstitutionRegistry.load()

        channel = registry.get("unr").official_channels[0]
        self.assertEqual("https://www.youtube.com/@UNROficial", channel.url)
        self.assertIsNone(channel.name)

    def test_pipeline_classifies_official_and_third_party_channels(self) -> None:
        queries = plan_queries(
            self.dictionary,
            institution="Universidad San Ignacio de Loyola",
            aliases=["USIL"],
            country="PE",
            indicators=["vida_campus"],
            max_queries=1,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            run_dir = run_search_pipeline(
                queries=queries,
                institution="Universidad San Ignacio de Loyola",
                aliases=["USIL"],
                country="PE",
                results_per_query=2,
                output_root=Path(temporary_directory),
                searcher=OfficialChannelSearcher(),
                min_sleep=0,
                max_sleep=0,
                institution_policy="strict",
                min_comments=0,
                official_channel_names=["USIL I Universidad San Ignacio de Loyola"],
                sleep=lambda _: None,
            )

            with (run_dir / "videos.csv").open(encoding="utf-8-sig", newline="") as source:
                selected = {
                    row["video_id"]: row["channel_classification"]
                    for row in csv.DictReader(source)
                }

            self.assertEqual("official", selected["off123def45"])
            self.assertEqual("third_party", selected["stu123def45"])


if __name__ == "__main__":
    unittest.main()
