from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .dictionary import KeywordDictionary, PROJECT_ROOT, normalize_text
from .institutions import Institution, InstitutionRegistry
from .pipeline import run_search_pipeline
from .planner import SearchQuery, plan_queries
from .yt_search import SearchDependencyError


DEFAULT_SUITE = PROJECT_ROOT / "config" / "experiments" / "keyword-dictionary-1.0.0.yaml"
SUMMARY_COLUMNS = (
    "profile_id",
    "dictionary_version",
    "scenario",
    "query_count",
    "combination_queries",
    "query_overlap_with_baseline",
    "novel_queries_vs_baseline",
    "results_per_query",
    "planned_results",
    "status",
    "raw_results",
    "discovered_unique_videos",
    "institution_matched",
    "institution_rejected",
    "institution_precision",
    "source_country_matched",
    "source_country_mismatched",
    "source_country_unknown",
    "source_country_rejected",
    "comment_count_qualified",
    "comment_count_rejected",
    "selected_videos",
    "selection_rate",
    "run_dir",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        data = yaml.safe_load(source)
    if not isinstance(data, dict):
        raise ValueError(f"La raiz de {path} debe ser un objeto YAML.")
    return data


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    normalized = normalize_text(value)
    return "_".join(part for part in normalized.split() if part)[:60] or "experimento"


def _deep_merge(current: Any, override: Any) -> Any:
    if isinstance(current, dict) and isinstance(override, dict):
        merged = copy.deepcopy(current)
        for key, value in override.items():
            merged[key] = _deep_merge(merged[key], value) if key in merged else copy.deepcopy(value)
        return merged
    return copy.deepcopy(override)


@dataclass(frozen=True)
class ExperimentProfile:
    id: str
    version: str
    label: str
    hypothesis: str
    inherits: tuple[str, ...]
    term_overrides: tuple[dict[str, Any], ...]
    additional_terms: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ExperimentScenario:
    id: str
    label: str
    profiles: tuple[str, ...]
    require_profile_selection: bool
    variants_per_term: int
    balance_by: str
    max_queries: int
    results_per_query: int


class KeywordExperimentSuite:
    def __init__(self, data: dict[str, Any], path: Path) -> None:
        if str(data.get("schema_version")) != "1.0":
            raise ValueError("La suite experimental requiere schema_version 1.0.")
        metadata = data.get("experiment")
        if not isinstance(metadata, dict):
            raise ValueError("Falta la seccion experiment en la suite.")

        self.data = data
        self.path = path.resolve()
        self.id = str(metadata["id"])
        self.label = str(metadata.get("label") or self.id)
        self.baseline_profile = str(metadata["baseline_profile"])
        base_path = Path(str(metadata["base_dictionary"]))
        self.base_dictionary_path = (
            base_path if base_path.is_absolute() else self.path.parent / base_path
        ).resolve()

        self.profiles = self._parse_profiles(data.get("profiles"))
        self.scenarios = self._parse_scenarios(data.get("scenarios"))
        if self.baseline_profile not in self.profiles:
            raise ValueError("El perfil baseline no existe en la suite.")
        self._validate_references()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "KeywordExperimentSuite":
        suite_path = Path(path) if path else DEFAULT_SUITE
        if not suite_path.is_absolute():
            suite_path = PROJECT_ROOT / suite_path
        suite_path = suite_path.resolve()
        return cls(_load_yaml(suite_path), suite_path)

    @staticmethod
    def _parse_profiles(value: Any) -> dict[str, ExperimentProfile]:
        if not isinstance(value, list) or not value:
            raise ValueError("profiles debe ser una lista no vacia.")
        profiles: dict[str, ExperimentProfile] = {}
        versions: set[str] = set()
        for row in value:
            if not isinstance(row, dict):
                raise ValueError("Cada perfil experimental debe ser un objeto.")
            profile_id = str(row["id"])
            version = str(row["version"])
            if profile_id in profiles:
                raise ValueError(f"Perfil experimental duplicado: {profile_id}")
            if version in versions:
                raise ValueError(f"Version experimental duplicada: {version}")
            versions.add(version)
            profiles[profile_id] = ExperimentProfile(
                id=profile_id,
                version=version,
                label=str(row.get("label") or profile_id),
                hypothesis=str(row.get("hypothesis") or ""),
                inherits=tuple(row.get("inherits") or ()),
                term_overrides=tuple(row.get("term_overrides") or ()),
                additional_terms=tuple(row.get("additional_terms") or ()),
            )
        return profiles

    @staticmethod
    def _parse_scenarios(value: Any) -> dict[str, ExperimentScenario]:
        if not isinstance(value, list) or not value:
            raise ValueError("scenarios debe ser una lista no vacia.")
        scenarios: dict[str, ExperimentScenario] = {}
        for row in value:
            if not isinstance(row, dict):
                raise ValueError("Cada escenario experimental debe ser un objeto.")
            scenario = ExperimentScenario(
                id=str(row["id"]),
                label=str(row.get("label") or row["id"]),
                profiles=tuple(row.get("profiles") or ()),
                require_profile_selection=bool(row.get("require_profile_selection", False)),
                variants_per_term=int(row["variants_per_term"]),
                balance_by=str(row.get("balance_by", "term")),
                max_queries=int(row["max_queries"]),
                results_per_query=int(row["results_per_query"]),
            )
            if scenario.id in scenarios:
                raise ValueError(f"Escenario experimental duplicado: {scenario.id}")
            if not scenario.profiles:
                raise ValueError(f"{scenario.id}: profiles no puede estar vacio.")
            if scenario.balance_by not in {"concept", "term"}:
                raise ValueError(f"{scenario.id}: balance_by debe ser concept o term.")
            if min(
                scenario.variants_per_term,
                scenario.max_queries,
                scenario.results_per_query,
            ) < 1:
                raise ValueError(f"{scenario.id}: los limites deben ser positivos.")
            scenarios[scenario.id] = scenario
        return scenarios

    def _validate_references(self) -> None:
        profile_ids = set(self.profiles)
        for profile in self.profiles.values():
            unknown = set(profile.inherits) - profile_ids
            if unknown:
                raise ValueError(f"{profile.id}: perfiles heredados desconocidos: {sorted(unknown)}")
        for scenario in self.scenarios.values():
            unknown = set(scenario.profiles) - profile_ids
            if unknown:
                raise ValueError(f"{scenario.id}: perfiles desconocidos: {sorted(unknown)}")

    def get_scenario(self, scenario_id: str) -> ExperimentScenario:
        try:
            return self.scenarios[scenario_id]
        except KeyError as exc:
            raise ValueError(
                f"Escenario desconocido: {scenario_id}. Opciones: {sorted(self.scenarios)}"
            ) from exc

    def build_dictionary(self, profile_id: str) -> KeywordDictionary:
        if profile_id not in self.profiles:
            raise ValueError(f"Perfil desconocido: {profile_id}.")
        data = copy.deepcopy(KeywordDictionary.load(self.base_dictionary_path).data)
        applied: set[str] = set()

        def apply_profile(current_id: str, stack: tuple[str, ...] = ()) -> None:
            if current_id in applied:
                return
            if current_id in stack:
                chain = " -> ".join((*stack, current_id))
                raise ValueError(f"Herencia circular de perfiles: {chain}")
            profile = self.profiles[current_id]
            for parent_id in profile.inherits:
                apply_profile(parent_id, (*stack, current_id))
            self._apply_profile(data, profile)
            applied.add(current_id)

        apply_profile(profile_id)
        profile = self.profiles[profile_id]
        data["dictionary"]["version"] = profile.version
        data["dictionary"]["status"] = "experimental"
        data["dictionary"]["updated_at"] = date.today().isoformat()
        data["experiment_profile"] = {
            "suite_id": self.id,
            "id": profile.id,
            "label": profile.label,
            "hypothesis": profile.hypothesis,
            "derived_from": str(self.base_dictionary_path),
            "applied_profiles": sorted(applied),
        }
        self._validate_derived_dictionary(data, profile.id)
        return KeywordDictionary(data, self.path)

    @staticmethod
    def _apply_profile(data: dict[str, Any], profile: ExperimentProfile) -> None:
        provenance_id = f"experiment_{profile.id}"
        provenance = data.setdefault("provenance", [])
        if not any(item.get("id") == provenance_id for item in provenance):
            provenance.append(
                {
                    "id": provenance_id,
                    "type": "experiment_profile",
                    "description": profile.hypothesis,
                }
            )

        terms = data["terms"]
        by_id = {term["id"]: term for term in terms}
        for override in profile.term_overrides:
            if not isinstance(override, dict) or "id" not in override:
                raise ValueError(f"{profile.id}: term_override invalido.")
            term_id = override["id"]
            if term_id not in by_id:
                raise ValueError(f"{profile.id}: termino a modificar no existe: {term_id}")
            merged = _deep_merge(by_id[term_id], override)
            index = terms.index(by_id[term_id])
            terms[index] = merged
            by_id[term_id] = merged

        for additional in profile.additional_terms:
            if not isinstance(additional, dict) or "id" not in additional:
                raise ValueError(f"{profile.id}: additional_term invalido.")
            term_id = additional["id"]
            if term_id in by_id:
                raise ValueError(f"{profile.id}: termino adicional duplicado: {term_id}")
            term = copy.deepcopy(additional)
            term.setdefault("provenance", provenance_id)
            terms.append(term)
            by_id[term_id] = term

    @staticmethod
    def _validate_derived_dictionary(data: dict[str, Any], profile_id: str) -> None:
        countries = {item["code"] for item in data["countries"]}
        term_ids = [term["id"] for term in data["terms"]]
        if len(term_ids) != len(set(term_ids)):
            raise ValueError(f"{profile_id}: el diccionario derivado contiene IDs duplicados.")
        known_terms = set(term_ids)
        for term in data["terms"]:
            restricted_countries = set(term.get("countries") or ())
            unknown_countries = restricted_countries - countries
            if unknown_countries:
                raise ValueError(
                    f"{term['id']}: paises restringidos desconocidos: {sorted(unknown_countries)}"
                )
            query_kind = term.get("query_kind", "single")
            if query_kind not in {"single", "combination"}:
                raise ValueError(f"{term['id']}: query_kind desconocido: {query_kind}")
            combines = term.get("combines") or []
            if query_kind == "combination":
                if len(combines) < 2:
                    raise ValueError(f"{term['id']}: una combinacion requiere al menos dos terminos.")
                unknown_terms = set(combines) - known_terms
                if unknown_terms:
                    raise ValueError(
                        f"{term['id']}: combina terminos desconocidos: {sorted(unknown_terms)}"
                    )


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.DictWriter(target, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _rate(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator:.4f}" if denominator else ""


def _load_manifest(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "run.json").read_text(encoding="utf-8"))


def _query_keys(queries: Iterable[SearchQuery]) -> set[str]:
    return {normalize_text(query.query) for query in queries}


def _write_video_comparison(
    experiment_dir: Path,
    profile_runs: dict[str, Path],
    baseline_profile: str,
) -> None:
    videos: dict[str, dict[str, Any]] = {}
    for profile_id, run_dir in profile_runs.items():
        raw_path = run_dir / "results_raw.jsonl"
        if raw_path.exists():
            for line in raw_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                video_id = record.get("video_id")
                if not video_id:
                    continue
                video = videos.setdefault(
                    video_id,
                    {
                        "video_id": video_id,
                        "url": record.get("url"),
                        "title": record.get("title"),
                        "channel": record.get("channel"),
                        "channel_country": record.get("channel_country"),
                        "found_by_profiles": set(),
                        "selected_by_profiles": set(),
                    },
                )
                video["found_by_profiles"].add(profile_id)

        selected_path = run_dir / "videos.csv"
        if selected_path.exists():
            with selected_path.open(encoding="utf-8-sig", newline="") as source:
                for row in csv.DictReader(source):
                    video_id = row.get("video_id")
                    if not video_id:
                        continue
                    video = videos.setdefault(
                        video_id,
                        {
                            "video_id": video_id,
                            "url": row.get("url"),
                            "title": row.get("title"),
                            "channel": row.get("channel"),
                            "channel_country": row.get("channel_country"),
                            "found_by_profiles": set(),
                            "selected_by_profiles": set(),
                        },
                    )
                    if row.get("channel_country"):
                        video["channel_country"] = row["channel_country"]
                    video["selected_by_profiles"].add(profile_id)

    columns = (
        "video_id",
        "url",
        "title",
        "channel",
        "channel_country",
        "found_by_profiles",
        "selected_by_profiles",
        "selected_count",
        "baseline_found",
        "baseline_selected",
        "manual_label",
        "manual_notes",
    )
    rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    for video in videos.values():
        found = sorted(video["found_by_profiles"])
        selected = sorted(video["selected_by_profiles"])
        row = {
            **video,
            "found_by_profiles": ";".join(found),
            "selected_by_profiles": ";".join(selected),
            "selected_count": len(selected),
            "baseline_found": baseline_profile in found,
            "baseline_selected": baseline_profile in selected,
            "manual_label": "",
            "manual_notes": "",
        }
        rows.append(row)
        if selected:
            review_rows.append(row)

    rows.sort(key=lambda row: (-row["selected_count"], row["video_id"]))
    review_rows.sort(key=lambda row: (-row["selected_count"], row["video_id"]))
    for filename, output_rows in (
        ("video_comparison.csv", rows),
        ("review_candidates.csv", review_rows),
    ):
        with (experiment_dir / filename).open("w", newline="", encoding="utf-8-sig") as target:
            writer = csv.DictWriter(target, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(output_rows)


def run_dictionary_experiment(
    *,
    suite: KeywordExperimentSuite,
    scenario_id: str,
    institution: str,
    aliases: list[str],
    country: str,
    output_root: Path,
    institution_record: Institution | None = None,
    institution_registry_version: str | None = None,
    indicators: Iterable[str] | None = None,
    profile_ids: Iterable[str] | None = None,
    execute: bool = False,
    min_comments: int = 75,
    published_after: date | None = date(2021, 12, 31),
    date_policy: str = "prefer",
    institution_policy: str = "strict",
    source_country_policy: str = "strict",
    min_sleep: float = 5.0,
    max_sleep: float = 10.0,
    retries: int = 2,
    metadata_min_sleep: float = 2.5,
    metadata_max_sleep: float = 5.0,
    metadata_workers: int = 1,
    youtube_api_key: str | None = None,
) -> Path:
    scenario = suite.get_scenario(scenario_id)
    if scenario.require_profile_selection and not profile_ids:
        raise ValueError(
            f"El escenario {scenario.id} requiere seleccionar un --profile."
        )
    selected_profiles = tuple(profile_ids or scenario.profiles)
    if len(selected_profiles) != len(set(selected_profiles)):
        raise ValueError("No repitas perfiles dentro del mismo experimento.")
    unknown_profiles = set(selected_profiles) - set(scenario.profiles)
    if unknown_profiles:
        raise ValueError(
            f"Perfiles fuera del escenario {scenario.id}: {sorted(unknown_profiles)}"
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    experiment_dir = output_root / f"{timestamp}_{_slug(institution)}_{scenario.id}"
    experiment_dir.mkdir(parents=True, exist_ok=False)
    shared_skip_cache = experiment_dir / "_metadata_skip_cache.json"

    baseline_dictionary = suite.build_dictionary(suite.baseline_profile)
    selected_indicators = tuple(indicators or baseline_dictionary.indicator_ids)
    baseline_queries = plan_queries(
        baseline_dictionary,
        institution=institution,
        aliases=aliases,
        country=country,
        indicators=selected_indicators,
        variants_per_term=scenario.variants_per_term,
        max_queries=scenario.max_queries,
        balance_by=scenario.balance_by,
    )
    baseline_query_keys = _query_keys(baseline_queries)

    experiment_manifest: dict[str, Any] = {
        "experiment_id": suite.id,
        "scenario": scenario.id,
        "status": "running" if execute else "planned",
        "started_at": _utc_now(),
        "completed_at": None,
        "institution": institution,
        "country": country,
        "aliases": aliases,
        "profiles": list(selected_profiles),
        "baseline_profile": suite.baseline_profile,
        "variants_per_term": scenario.variants_per_term,
        "balance_by": scenario.balance_by,
        "max_queries": scenario.max_queries,
        "results_per_query": scenario.results_per_query,
        "min_comments": min_comments,
        "published_after": published_after.isoformat() if published_after else None,
        "date_policy": date_policy,
        "institution_policy": institution_policy,
        "source_country_policy": source_country_policy,
        "execute": execute,
        "runs": [],
    }
    _write_json(experiment_dir / "experiment.json", experiment_manifest)

    summary_rows: list[dict[str, Any]] = []
    profile_runs: dict[str, Path] = {}
    for position, profile_id in enumerate(selected_profiles, 1):
        profile = suite.profiles[profile_id]
        dictionary = suite.build_dictionary(profile_id)
        queries = plan_queries(
            dictionary,
            institution=institution,
            aliases=aliases,
            country=country,
            indicators=selected_indicators,
            variants_per_term=scenario.variants_per_term,
            max_queries=scenario.max_queries,
            balance_by=scenario.balance_by,
        )
        query_keys = _query_keys(queries)
        overlap = len(query_keys & baseline_query_keys)
        combination_count = sum(query.query_kind == "combination" for query in queries)
        print(
            f"[{position}/{len(selected_profiles)}] {profile_id} v{profile.version}: "
            f"{len(queries)} consultas ({combination_count} combinaciones)"
        )

        run_dir = run_search_pipeline(
            queries=queries,
            institution=institution,
            aliases=aliases,
            country=country,
            results_per_query=scenario.results_per_query,
            output_root=experiment_dir / profile_id,
            dry_run=not execute,
            min_sleep=min_sleep,
            max_sleep=max_sleep,
            retries=retries,
            published_after=published_after,
            date_policy=date_policy,
            institution_policy=institution_policy,
            source_country_policy=source_country_policy,
            metadata_min_sleep=metadata_min_sleep,
            metadata_max_sleep=metadata_max_sleep,
            metadata_workers=metadata_workers,
            metadata_skip_cache=shared_skip_cache,
            min_comments=min_comments,
            youtube_api_key=youtube_api_key,
            institution_registry_version=institution_registry_version,
            institution_id=institution_record.id if institution_record else None,
            institution_eligibility=(
                {
                    "national": institution_record.national,
                    "licensed": institution_record.licensed,
                    "qs_ranked": institution_record.qs_ranked,
                    "verification_status": institution_record.verification_status,
                }
                if institution_record
                else None
            ),
            experiment_id=suite.id,
            experiment_scenario=scenario.id,
            experiment_profile=profile.id,
            official_channel_ids=(
                list(institution_record.official_channel_ids) if institution_record else None
            ),
            official_channel_names=(
                list(institution_record.official_channel_names) if institution_record else None
            ),
        )
        profile_runs[profile_id] = run_dir
        manifest = _load_manifest(run_dir)
        discovered = int(manifest.get("discovered_unique_videos") or 0)
        matched = int(manifest.get("institution_matched") or 0)
        selected = int(manifest.get("unique_videos") or 0)
        summary_rows.append(
            {
                "profile_id": profile.id,
                "dictionary_version": profile.version,
                "scenario": scenario.id,
                "query_count": len(queries),
                "combination_queries": combination_count,
                "query_overlap_with_baseline": overlap,
                "novel_queries_vs_baseline": len(query_keys - baseline_query_keys),
                "results_per_query": scenario.results_per_query,
                "planned_results": len(queries) * scenario.results_per_query,
                "status": manifest.get("status"),
                "raw_results": manifest.get("raw_results", 0),
                "discovered_unique_videos": discovered,
                "institution_matched": matched,
                "institution_rejected": manifest.get("institution_rejected", 0),
                "institution_precision": _rate(matched, discovered),
                "source_country_matched": manifest.get("source_country_matched", 0),
                "source_country_mismatched": manifest.get("source_country_mismatched", 0),
                "source_country_unknown": manifest.get("source_country_unknown", 0),
                "source_country_rejected": manifest.get("source_country_rejected", 0),
                "comment_count_qualified": manifest.get("comment_count_qualified", 0),
                "comment_count_rejected": manifest.get("comment_count_rejected", 0),
                "selected_videos": selected,
                "selection_rate": _rate(selected, discovered),
                "run_dir": str(run_dir.relative_to(experiment_dir)),
            }
        )
        experiment_manifest["runs"].append(
            {
                "profile_id": profile.id,
                "dictionary_version": profile.version,
                "run_dir": str(run_dir.relative_to(experiment_dir)),
            }
        )
        _write_summary(experiment_dir / "summary.csv", summary_rows)
        _write_json(experiment_dir / "experiment.json", experiment_manifest)

    if execute:
        _write_video_comparison(experiment_dir, profile_runs, suite.baseline_profile)
    experiment_manifest["status"] = "completed" if execute else "planned"
    experiment_manifest["completed_at"] = _utc_now()
    _write_json(experiment_dir / "experiment.json", experiment_manifest)
    return experiment_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compara perfiles versionados del diccionario de keywords."
    )
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--scenario", default="controlled")
    parser.add_argument("--profile", action="append", help="Perfil del escenario; repetible.")
    parser.add_argument("--institution-id")
    parser.add_argument("--institutions")
    parser.add_argument("--require-eligible", action="store_true")
    parser.add_argument("--require-national", action="store_true")
    parser.add_argument("--institution")
    parser.add_argument("--alias", action="append", default=[])
    parser.add_argument("--country")
    parser.add_argument("--indicator", action="append")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Ejecuta busquedas. Sin este flag solo genera los cinco planes.",
    )
    parser.add_argument("--min-comments", type=int, default=75)
    parser.add_argument("--published-after", type=date.fromisoformat, default=date(2021, 12, 31))
    parser.add_argument("--date-policy", choices=("prefer", "strict"), default="prefer")
    parser.add_argument(
        "--institution-policy", choices=("strict", "prefer", "off"), default="strict"
    )
    parser.add_argument(
        "--source-country-policy",
        choices=("strict", "prefer", "off"),
        default="strict",
    )
    parser.add_argument("--min-sleep", type=float, default=5.0)
    parser.add_argument("--max-sleep", type=float, default=10.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--metadata-min-sleep", type=float, default=2.5)
    parser.add_argument("--metadata-max-sleep", type=float, default=5.0)
    parser.add_argument("--metadata-workers", type=int, default=1)
    parser.add_argument("--youtube-api-key", default=os.getenv("YOUTUBE_API_KEY"))
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "experiments")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        suite = KeywordExperimentSuite.load(args.suite)
        registry = None
        institution_record = None
        if args.institution_id:
            registry = InstitutionRegistry.load(args.institutions)
            institution_record = registry.get(
                args.institution_id,
                require_eligible=args.require_eligible,
                require_national=args.require_national,
            )
            args.institution = institution_record.name
            args.alias = list(institution_record.aliases) + list(args.alias)
            args.country = institution_record.country
        if not args.institution or not args.country:
            raise ValueError("Debes indicar --institution-id o --institution y --country.")

        experiment_dir = run_dictionary_experiment(
            suite=suite,
            scenario_id=args.scenario,
            institution=args.institution,
            aliases=args.alias,
            country=args.country.upper(),
            output_root=args.output_dir,
            institution_record=institution_record,
            institution_registry_version=registry.version if registry else None,
            indicators=args.indicator,
            profile_ids=args.profile,
            execute=args.execute,
            min_comments=args.min_comments,
            published_after=args.published_after,
            date_policy=args.date_policy,
            institution_policy=args.institution_policy,
            source_country_policy=args.source_country_policy,
            min_sleep=args.min_sleep,
            max_sleep=args.max_sleep,
            retries=args.retries,
            metadata_min_sleep=args.metadata_min_sleep,
            metadata_max_sleep=args.metadata_max_sleep,
            metadata_workers=args.metadata_workers,
            youtube_api_key=args.youtube_api_key,
        )
    except (ValueError, KeyError, OSError, SearchDependencyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    mode = "ejecutado" if args.execute else "planificado"
    print(f"Experimento {mode} en: {experiment_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
