from __future__ import annotations

import csv
import json
import random
import re
import time
import unicodedata
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .dictionary import normalize_text
from .planner import SearchQuery
from .yt_search import SearchDependencyError, SearchExecutionError, SearchHit, YtDlpSearcher


QUERY_COLUMNS = (
    "query_id",
    "query",
    "institution_alias",
    "country",
    "indicator",
    "concept",
    "term_id",
    "term",
    "locale",
    "intents",
    "score",
    "dictionary_version",
)

VIDEO_COLUMNS = (
    "video_id",
    "url",
    "title",
    "channel",
    "channel_id",
    "duration",
    "view_count",
    "comment_count",
    "upload_date",
    "published_after_match",
    "institution_match",
    "matched_aliases",
    "channel_classification",
    "metadata_error",
    "live_status",
    "best_rank",
    "occurrences",
    "query_ids",
    "indicators",
    "concepts",
    "term_ids",
)

REJECTED_COLUMNS = (*VIDEO_COLUMNS, "rejection_reason")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_value).strip("_").lower()
    return slug[:60] or "institucion"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_queries(path: Path, queries: list[SearchQuery]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.DictWriter(target, fieldnames=QUERY_COLUMNS)
        writer.writeheader()
        writer.writerows(query.as_row() for query in queries)


def _merge_hit(
    videos: dict[str, dict[str, Any]],
    hit: SearchHit,
    query: SearchQuery,
    rank: int,
) -> None:
    if hit.video_id not in videos:
        videos[hit.video_id] = {
            **asdict(hit),
            "best_rank": rank,
            "occurrences": 0,
            "query_ids": set(),
            "indicators": set(),
            "concepts": set(),
            "term_ids": set(),
        }

    video = videos[hit.video_id]
    for field, value in asdict(hit).items():
        if video.get(field) in (None, "") and value not in (None, ""):
            video[field] = value
    video["best_rank"] = min(video["best_rank"], rank)
    video["occurrences"] += 1
    video["query_ids"].add(query.query_id)
    video["indicators"].add(query.indicator)
    video["concepts"].add(query.concept)
    video["term_ids"].add(query.term_id)


def _write_videos(
    path: Path,
    videos: dict[str, dict[str, Any]],
    columns: tuple[str, ...] = VIDEO_COLUMNS,
) -> None:
    rows: list[dict[str, Any]] = []
    for video in videos.values():
        row = dict(video)
        for field in ("query_ids", "indicators", "concepts", "term_ids"):
            row[field] = ";".join(sorted(row[field]))
        rows.append(row)

    date_priority = {True: 0, None: 1, False: 2}
    institution_priority = {True: 0, None: 1, False: 2}
    rows.sort(
        key=lambda item: (
            institution_priority[item.get("institution_match")],
            date_priority[item.get("published_after_match")],
            -item["occurrences"],
            item["best_rank"],
            item["video_id"],
        )
    )
    with path.open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.DictWriter(target, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _published_after_match(upload_date: str | None, cutoff: date) -> bool | None:
    if not upload_date:
        return None
    try:
        published = datetime.strptime(upload_date, "%Y%m%d").date()
    except ValueError:
        return None
    return published > cutoff


def _hit_from_video(video: dict[str, Any]) -> SearchHit:
    return SearchHit(
        video_id=video["video_id"],
        url=video["url"],
        title=video["title"],
        channel=video.get("channel"),
        channel_id=video.get("channel_id"),
        duration=video.get("duration"),
        view_count=video.get("view_count"),
        comment_count=video.get("comment_count"),
        upload_date=video.get("upload_date"),
        live_status=video.get("live_status"),
        description=video.get("description"),
    )


def _matched_institution_aliases(
    video: dict[str, Any], institution: str, aliases: list[str]
) -> list[str]:
    title_description_text = normalize_text(
        " ".join(
            value
            for value in (video.get("title"), video.get("description"))
            if isinstance(value, str)
        )
    )
    channel_text = normalize_text(video.get("channel") or "")
    matched: list[str] = []
    seen: set[str] = set()
    for alias in (institution, *aliases):
        normalized_alias = normalize_text(alias)
        if not normalized_alias or normalized_alias in seen:
            continue
        seen.add(normalized_alias)
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_alias)}(?![a-z0-9])"
        if re.search(pattern, title_description_text) or re.search(pattern, channel_text):
            matched.append(alias)
            continue
        compact_alias = re.sub(r"[^a-z0-9]+", "", normalized_alias)
        compact_channel = re.sub(r"[^a-z0-9]+", "", channel_text)
        if len(compact_alias) >= 4 and compact_alias in compact_channel:
            matched.append(alias)
    return matched


def _is_unavailable_metadata_error(error: str | None) -> bool:
    if not error:
        return False
    normalized = normalize_text(error)
    unavailable_markers = (
        "not available",
        "unavailable",
        "private video",
        "video is private",
        "removed",
    )
    return any(marker in normalized for marker in unavailable_markers)


def _classify_channel(
    video: dict[str, Any],
    *,
    official_channel_ids: list[str] | None,
    official_channel_names: list[str] | None,
) -> str:
    channel_id = video.get("channel_id")
    if channel_id and official_channel_ids and channel_id in official_channel_ids:
        return "official"

    channel_name = normalize_text(video.get("channel") or "")
    for official_name in official_channel_names or []:
        normalized_name = normalize_text(official_name)
        if not normalized_name:
            continue
        if channel_name == normalized_name or normalized_name in channel_name:
            return "official"

    return "third_party" if channel_name else "unclassified"


def run_search_pipeline(
    *,
    queries: list[SearchQuery],
    institution: str,
    aliases: list[str],
    country: str,
    results_per_query: int,
    output_root: Path,
    dry_run: bool = False,
    min_sleep: float = 5.0,
    max_sleep: float = 10.0,
    retries: int = 2,
    published_after: date | None = None,
    date_policy: str = "prefer",
    institution_policy: str = "strict",
    metadata_min_sleep: float = 2.5,
    metadata_max_sleep: float = 5.0,
    institution_registry_version: str | None = None,
    institution_id: str | None = None,
    institution_eligibility: dict[str, Any] | None = None,
    official_channel_ids: list[str] | None = None,
    official_channel_names: list[str] | None = None,
    searcher: YtDlpSearcher | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    if not queries:
        raise ValueError("El plan no contiene consultas.")
    if results_per_query < 1:
        raise ValueError("results_per_query debe ser mayor que cero.")
    if min_sleep < 0 or max_sleep < min_sleep:
        raise ValueError("El rango de espera es invalido.")
    if metadata_min_sleep < 0 or metadata_max_sleep < metadata_min_sleep:
        raise ValueError("El rango de espera de metadatos es invalido.")
    if date_policy not in {"prefer", "strict"}:
        raise ValueError("date_policy debe ser 'prefer' o 'strict'.")
    if institution_policy not in {"strict", "prefer", "off"}:
        raise ValueError("institution_policy debe ser 'strict', 'prefer' u 'off'.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    indicator_slug = "-".join(sorted({query.indicator for query in queries}))
    run_dir = output_root / f"{timestamp}_{_slug(institution)}_{indicator_slug}"
    run_dir.mkdir(parents=True, exist_ok=False)

    _write_queries(run_dir / "queries.csv", queries)
    manifest: dict[str, Any] = {
        "run_id": run_dir.name,
        "status": "planned" if dry_run else "running",
        "started_at": _utc_now(),
        "completed_at": None,
        "dictionary_version": queries[0].dictionary_version,
        "institution_registry_version": institution_registry_version,
        "institution_id": institution_id,
        "institution_eligibility": institution_eligibility,
        "institution": institution,
        "aliases": aliases,
        "country": country,
        "indicators": sorted({query.indicator for query in queries}),
        "concepts": sorted({query.concept for query in queries}),
        "query_count": len(queries),
        "results_per_query": results_per_query,
        "queries_completed": 0,
        "raw_results": 0,
        "unique_videos": 0,
        "discovered_unique_videos": 0,
        "metadata_enriched": 0,
        "published_after": published_after.isoformat() if published_after else None,
        "date_policy": date_policy if published_after else None,
        "date_preferred": 0,
        "date_older": 0,
        "date_unknown": 0,
        "institution_policy": institution_policy,
        "institution_matched": 0,
        "institution_rejected": 0,
        "official_channel_count": len(official_channel_ids or official_channel_names or []),
        "errors": [],
        "dry_run": dry_run,
    }
    _write_json(run_dir / "run.json", manifest)

    if dry_run:
        manifest["completed_at"] = _utc_now()
        _write_json(run_dir / "run.json", manifest)
        return run_dir

    active_searcher = searcher or YtDlpSearcher(retries=retries)
    videos: dict[str, dict[str, Any]] = {}
    raw_path = run_dir / "results_raw.jsonl"

    try:
        with raw_path.open("w", encoding="utf-8") as raw_file:
            for position, query in enumerate(queries, 1):
                print(f"[{position}/{len(queries)}] {query.query}")
                try:
                    hits = active_searcher.search(query.query, results_per_query)
                except SearchExecutionError as exc:
                    manifest["errors"].append(
                        {"query_id": query.query_id, "message": str(exc)}
                    )
                    hits = []

                for rank, hit in enumerate(hits, 1):
                    record = {
                        "query_id": query.query_id,
                        "query": query.query,
                        "indicator": query.indicator,
                        "concept": query.concept,
                        "term_id": query.term_id,
                        "rank": rank,
                        **asdict(hit),
                    }
                    raw_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                    _merge_hit(videos, hit, query, rank)
                raw_file.flush()

                manifest["queries_completed"] = position
                manifest["raw_results"] += len(hits)
                manifest["unique_videos"] = len(videos)
                _write_json(run_dir / "run.json", manifest)

                if position < len(queries):
                    sleep(random.uniform(min_sleep, max_sleep))

        manifest["discovered_unique_videos"] = len(videos)
        if published_after or institution_policy != "off":
            pending_metadata = [
                video
                for video in videos.values()
                if (published_after and not video.get("upload_date"))
                or (
                    institution_policy != "off"
                    and not video.get("description")
                    and not _matched_institution_aliases(video, institution, aliases)
                )
            ]
            for position, video in enumerate(pending_metadata, 1):
                print(
                    f"[metadata {position}/{len(pending_metadata)}] "
                    f"{video['video_id']}"
                )
                try:
                    enriched = active_searcher.enrich(_hit_from_video(video))
                except SearchExecutionError as exc:
                    video["metadata_error"] = str(exc)
                    manifest["errors"].append(
                        {
                            "stage": "metadata",
                            "video_id": video["video_id"],
                            "message": str(exc),
                        }
                    )
                else:
                    for field, value in asdict(enriched).items():
                        if value not in (None, ""):
                            video[field] = value
                    manifest["metadata_enriched"] += 1

                if position < len(pending_metadata):
                    sleep(random.uniform(metadata_min_sleep, metadata_max_sleep))

        if published_after:
            for video in videos.values():
                video["published_after_match"] = _published_after_match(
                    video.get("upload_date"), published_after
                )
            manifest["date_preferred"] = sum(
                video["published_after_match"] is True for video in videos.values()
            )
            manifest["date_older"] = sum(
                video["published_after_match"] is False for video in videos.values()
            )
            manifest["date_unknown"] = sum(
                video["published_after_match"] is None for video in videos.values()
            )
        else:
            for video in videos.values():
                video["published_after_match"] = None

        for video in videos.values():
            matched_aliases = (
                _matched_institution_aliases(video, institution, aliases)
                if institution_policy != "off"
                else []
            )
            video["institution_match"] = bool(matched_aliases) if institution_policy != "off" else None
            video["matched_aliases"] = ";".join(matched_aliases)
            video["channel_classification"] = _classify_channel(
                video,
                official_channel_ids=official_channel_ids,
                official_channel_names=official_channel_names,
            )

        manifest["institution_matched"] = sum(
            video["institution_match"] is True for video in videos.values()
        )
        rejected_videos: dict[str, dict[str, Any]] = {}
        if institution_policy == "strict":
            rejected_videos = {
                video_id: {**video, "rejection_reason": "institution_not_found_in_metadata"}
                for video_id, video in videos.items()
                if video["institution_match"] is not True
            }
            videos = {
                video_id: video
                for video_id, video in videos.items()
                if video["institution_match"] is True
            }
            unavailable_videos = {
                video_id: {**video, "rejection_reason": "metadata_unavailable"}
                for video_id, video in videos.items()
                if _is_unavailable_metadata_error(video.get("metadata_error"))
            }
            rejected_videos.update(unavailable_videos)
            videos = {
                video_id: video
                for video_id, video in videos.items()
                if video_id not in unavailable_videos
            }
        manifest["institution_rejected"] = len(rejected_videos)

        if published_after and date_policy == "strict":
            rejected_by_date = {
                video_id: {**video, "rejection_reason": "published_on_or_before_cutoff"}
                for video_id, video in videos.items()
                if video["published_after_match"] is not True
            }
            rejected_videos.update(rejected_by_date)
            videos = {
                video_id: video
                for video_id, video in videos.items()
                if video["published_after_match"] is True
            }

        manifest["unique_videos"] = len(videos)
    except KeyboardInterrupt:
        manifest["status"] = "interrupted"
        raise
    except SearchDependencyError:
        manifest["status"] = "failed"
        raise
    except Exception:
        manifest["status"] = "failed"
        raise
    finally:
        _write_videos(run_dir / "videos.csv", videos)
        if "rejected_videos" in locals() and rejected_videos:
            _write_videos(
                run_dir / "rejected.csv",
                rejected_videos,
                columns=REJECTED_COLUMNS,
            )
        manifest["completed_at"] = _utc_now()
        if manifest["status"] == "running":
            manifest["status"] = "completed_with_errors" if manifest["errors"] else "completed"
        _write_json(run_dir / "run.json", manifest)

    return run_dir
