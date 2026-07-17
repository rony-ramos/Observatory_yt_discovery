from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .dictionary import PROJECT_ROOT, normalize_text
from .yt_search import SearchDependencyError


VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
VIDEO_ID_HEADERS = {"videoid", "idvideo", "youtubeid", "idyoutube"}
VIDEO_URL_HEADERS = {"url", "videourl", "youtubeurl", "enlace", "link"}
INSTITUTION_HEADERS = {"institucion", "universidad", "institution"}


@dataclass(frozen=True)
class VideoRequest:
    video_id: str
    url: str
    row_number: int
    institution: str


@dataclass(frozen=True)
class DownloadResult:
    video_id: str
    url: str
    row_number: int
    institution: str
    status: str
    file_path: str | None = None
    error: str | None = None


def _header_key(value: Any) -> str:
    return normalize_text(str(value or "")).replace("_", "").replace("-", "")


def _video_id_from_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if VIDEO_ID_PATTERN.fullmatch(candidate):
        return candidate

    parsed = urlparse(candidate)
    if parsed.netloc.lower().endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0]
    elif "youtube.com" in parsed.netloc.lower():
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if not video_id:
            path_parts = [part for part in parsed.path.split("/") if part]
            video_id = path_parts[-1] if path_parts and path_parts[0] in {"shorts", "embed"} else ""
    else:
        return None
    return video_id if VIDEO_ID_PATTERN.fullmatch(video_id) else None


def _institution_folder(institution: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", normalize_text(institution)).strip("_")
    return slug or "sin_institucion"


def _load_workbook_rows(input_path: Path, sheet_name: str | None) -> list[tuple[int, dict[str, Any]]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise SearchDependencyError(
            "Falta openpyxl. Instala las dependencias con: pip install -r requirements.txt"
        ) from exc

    workbook = load_workbook(input_path, read_only=True, data_only=True)
    try:
        if sheet_name:
            if sheet_name not in workbook.sheetnames:
                raise ValueError(
                    f"La hoja {sheet_name!r} no existe. Opciones: {workbook.sheetnames}"
                )
            sheet = workbook[sheet_name]
        else:
            sheet = workbook.active

        rows = sheet.iter_rows(values_only=True)
        headers = next(rows, None)
        if not headers:
            raise ValueError("El archivo XLSX no contiene encabezados.")

        indexed_headers = {
            _header_key(header): index
            for index, header in enumerate(headers)
            if header not in (None, "")
        }
        video_id_index = next(
            (indexed_headers[header] for header in VIDEO_ID_HEADERS if header in indexed_headers),
            None,
        )
        video_url_index = next(
            (indexed_headers[header] for header in VIDEO_URL_HEADERS if header in indexed_headers),
            None,
        )
        institution_index = next(
            (indexed_headers[header] for header in INSTITUTION_HEADERS if header in indexed_headers),
            None,
        )
        if video_id_index is None and video_url_index is None:
            raise ValueError(
                "No se encontro una columna de video. Usa Video_id, video_id, url o youtube_url."
            )
        if institution_index is None:
            raise ValueError(
                "No se encontro una columna de institucion. Usa Institucion, universidad o institution."
            )

        def cell_value(row: tuple[Any, ...], index: int | None) -> Any:
            return row[index] if index is not None and index < len(row) else None

        loaded_rows: list[tuple[int, dict[str, Any]]] = []
        for row_number, row in enumerate(rows, start=2):
            loaded_rows.append(
                (
                    row_number,
                    {
                        "video_id": cell_value(row, video_id_index),
                        "url": cell_value(row, video_url_index),
                        "institution": cell_value(row, institution_index),
                    },
                )
            )
        return loaded_rows
    finally:
        workbook.close()


def load_video_requests(input_path: Path, sheet_name: str | None = None) -> list[VideoRequest]:
    if not input_path.is_file():
        raise ValueError(f"No existe el archivo de entrada: {input_path}")
    if input_path.suffix.lower() != ".xlsx":
        raise ValueError("El archivo de entrada debe tener extension .xlsx.")

    requests: list[VideoRequest] = []
    seen: set[tuple[str, str]] = set()
    for row_number, row in _load_workbook_rows(input_path, sheet_name):
        video_id = _video_id_from_value(row["video_id"]) or _video_id_from_value(row["url"])
        institution = str(row["institution"] or "").strip()
        deduplication_key = (video_id or "", _institution_folder(institution))
        if not video_id or deduplication_key in seen:
            continue
        seen.add(deduplication_key)
        requests.append(
            VideoRequest(
                video_id=video_id,
                url=f"https://www.youtube.com/watch?v={video_id}",
                row_number=row_number,
                institution=institution,
            )
        )
    if not requests:
        raise ValueError("No se encontraron IDs o URLs de YouTube validos en el XLSX.")
    return requests


def _download_one(
    request: VideoRequest,
    *,
    download_root: Path,
    video_format: str,
    retries: int,
    cookies_from_browser: str | None,
    cookies_browser_profile: str | None,
) -> DownloadResult:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError as exc:
        raise SearchDependencyError(
            "Falta yt-dlp. Instala las dependencias con: pip install -r requirements.txt"
        ) from exc

    output_dir = download_root / _institution_folder(request.institution)
    output_dir.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {
        "format": video_format,
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "continuedl": True,
        "overwrites": False,
        "retries": retries,
        "fragment_retries": retries,
        "quiet": True,
        "no_warnings": True,
    }
    if cookies_from_browser:
        options["cookiesfrombrowser"] = (
            cookies_from_browser,
            cookies_browser_profile,
            None,
            None,
        )

    try:
        with YoutubeDL(options) as ydl:
            ydl.extract_info(request.url, download=True)
    except DownloadError as exc:
        return DownloadResult(
            video_id=request.video_id,
            url=request.url,
            row_number=request.row_number,
            institution=request.institution,
            status="failed",
            error=str(exc),
        )

    downloaded_files = sorted(
        path
        for path in output_dir.glob(f"{request.video_id}.*")
        if path.suffix not in {".part", ".ytdl", ".json"}
    )
    return DownloadResult(
        video_id=request.video_id,
        url=request.url,
        row_number=request.row_number,
        institution=request.institution,
        status="completed",
        file_path=str(downloaded_files[0]) if downloaded_files else None,
    )


async def download_videos(
    requests: list[VideoRequest],
    *,
    download_root: Path,
    workers: int = 1,
    video_format: str = "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[ext=mp4]/b",
    retries: int = 0,
    cookies_from_browser: str | None = None,
    cookies_browser_profile: str | None = None,
) -> list[DownloadResult]:
    if workers < 1:
        raise ValueError("workers debe ser mayor que cero.")
    if retries < 0:
        raise ValueError("retries no puede ser negativo.")

    download_root.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(workers)

    async def run_one(request: VideoRequest) -> DownloadResult:
        async with semaphore:
            return await asyncio.to_thread(
                _download_one,
                request,
                download_root=download_root,
                video_format=video_format,
                retries=retries,
                cookies_from_browser=cookies_from_browser,
                cookies_browser_profile=cookies_browser_profile,
            )

    return await asyncio.gather(*(run_one(request) for request in requests))


def _write_report(report_dir: Path, results: list[DownloadResult]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    fields = ["video_id", "url", "row_number", "institution", "status", "file_path", "error"]
    with (report_dir / "downloads.csv").open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(result) for result in results)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requested": len(results),
        "completed": sum(result.status == "completed" for result in results),
        "failed": sum(result.status == "failed" for result in results),
    }
    (report_dir / "download_run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Descarga videos de YouTube listados en un archivo XLSX."
    )
    parser.add_argument("--input", type=Path, required=True, help="Ruta al archivo XLSX.")
    parser.add_argument("--sheet", help="Hoja del XLSX. Por defecto usa la hoja activa.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Carpeta raiz de descarga. Por defecto: downloads/.",
    )
    parser.add_argument("--workers", type=int, default=1, help="Descargas simultaneas.")
    parser.add_argument("--retries", type=int, default=0, help="Reintentos por video.")
    parser.add_argument(
        "--format",
        dest="video_format",
        default="bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]/b[ext=mp4]/b",
        help="Selector de formato de yt-dlp. Por defecto limita video a 720p.",
    )
    parser.add_argument("--cookies-from-browser", help="Por ejemplo: chrome, edge o firefox.")
    parser.add_argument("--cookies-browser-profile", help="Por ejemplo: Default o Profile 1.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        input_path = args.input.resolve()
        download_root = (
            args.output_dir.resolve()
            if args.output_dir
            else PROJECT_ROOT / "downloads"
        )
        requests = load_video_requests(input_path, args.sheet)
        print(f"Plan: {len(requests)} videos, salida: {download_root}")
        results = asyncio.run(
            download_videos(
                requests,
                download_root=download_root,
                workers=args.workers,
                video_format=args.video_format,
                retries=args.retries,
                cookies_from_browser=args.cookies_from_browser,
                cookies_browser_profile=args.cookies_browser_profile,
            )
        )
        report_dir = (
            download_root
            / "_reports"
            / f"{input_path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        _write_report(report_dir, results)
    except (OSError, ValueError, SearchDependencyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    completed = sum(result.status == "completed" for result in results)
    print(f"Descarga terminada: {completed}/{len(results)} videos. Reporte: {report_dir / 'downloads.csv'}")
    return 0 if completed == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
