from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "config" / "keywords" / "manifest.yaml"


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(without_marks.split())


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        data = yaml.safe_load(source)
    if not isinstance(data, dict):
        raise ValueError(f"La raiz de {path} debe ser un objeto YAML.")
    return data


@dataclass(frozen=True)
class KeywordVariant:
    term_id: str
    indicator: str
    concept: str
    phrase: str
    locale: str
    intents: tuple[str, ...]
    status: str
    weight: float
    query_kind: str = "single"
    combination_id: str | None = None
    combines: tuple[str, ...] = ()


class KeywordDictionary:
    def __init__(self, data: dict[str, Any], path: Path) -> None:
        self.data = data
        self.path = path
        self.version = str(data["dictionary"]["version"])
        self.country_codes = tuple(item["code"] for item in data["countries"])
        self.intent_ids = tuple(item["id"] for item in data["intents"])
        self.indicator_ids = tuple(item["id"] for item in data["indicators"])
        experiment = data.get("experiment_profile") or {}
        self.experiment_profile_id = experiment.get("id")
        self.concept_to_indicator = {
            concept["id"]: indicator["id"]
            for indicator in data["indicators"]
            for concept in indicator["concepts"]
        }

    @classmethod
    def load(cls, path: str | Path | None = None) -> "KeywordDictionary":
        if path is None:
            manifest = _load_yaml(DEFAULT_MANIFEST)
            active_version = manifest["active_version"]
            active_file = next(
                item["file"]
                for item in manifest["versions"]
                if item["version"] == active_version
            )
            dictionary_path = DEFAULT_MANIFEST.parent / active_file
        else:
            dictionary_path = Path(path)
            if not dictionary_path.is_absolute():
                dictionary_path = PROJECT_ROOT / dictionary_path

        dictionary_path = dictionary_path.resolve()
        return cls(_load_yaml(dictionary_path), dictionary_path)

    def validate_selection(
        self,
        country: str,
        indicators: Iterable[str],
        concepts: Iterable[str] | None,
        intents: Iterable[str] | None,
    ) -> None:
        if country not in self.country_codes:
            raise ValueError(f"Pais no soportado: {country}. Opciones: {self.country_codes}")

        unknown_indicators = set(indicators) - set(self.indicator_ids)
        if unknown_indicators:
            raise ValueError(f"Indicadores desconocidos: {sorted(unknown_indicators)}")

        if concepts:
            unknown_concepts = set(concepts) - set(self.concept_to_indicator)
            if unknown_concepts:
                raise ValueError(f"Conceptos desconocidos: {sorted(unknown_concepts)}")
            incompatible = {
                concept
                for concept in concepts
                if self.concept_to_indicator[concept] not in indicators
            }
            if incompatible:
                raise ValueError(
                    "Los conceptos no pertenecen a los indicadores elegidos: "
                    f"{sorted(incompatible)}"
                )

        if intents:
            unknown_intents = set(intents) - set(self.intent_ids)
            if unknown_intents:
                raise ValueError(f"Intenciones desconocidas: {sorted(unknown_intents)}")

    def iter_variants(
        self,
        *,
        country: str,
        indicators: Iterable[str],
        concepts: Iterable[str] | None = None,
        intents: Iterable[str] | None = None,
        statuses: Iterable[str] = ("seed", "validated"),
    ) -> list[KeywordVariant]:
        indicator_set = set(indicators)
        concept_set = set(concepts or ())
        intent_set = set(intents or ())
        status_set = set(statuses)
        self.validate_selection(country, indicator_set, concept_set or None, intent_set or None)

        variants: list[KeywordVariant] = []
        for term in self.data["terms"]:
            if term["indicator"] not in indicator_set:
                continue
            if concept_set and term["concept"] not in concept_set:
                continue
            term_countries = set(term.get("countries") or ())
            if term_countries and country not in term_countries:
                continue
            if term["status"] not in status_set:
                continue
            if intent_set and not intent_set.intersection(term["intents"]):
                continue

            seen: set[str] = set()
            scoped_variants = (
                (country, term["variants"].get(country, [])),
                ("global", term["variants"].get("global", [])),
            )
            for locale, phrases in scoped_variants:
                for phrase in phrases:
                    normalized = normalize_text(phrase)
                    if normalized in seen:
                        continue
                    seen.add(normalized)
                    variants.append(
                        KeywordVariant(
                            term_id=term["id"],
                            indicator=term["indicator"],
                            concept=term["concept"],
                            phrase=phrase,
                            locale=locale,
                            intents=tuple(term["intents"]),
                            status=term["status"],
                            weight=float(term["search_weight"]),
                            query_kind=str(term.get("query_kind", "single")),
                            combination_id=(
                                term["id"] if term.get("query_kind") == "combination" else None
                            ),
                            combines=tuple(term.get("combines") or ()),
                        )
                    )
        return variants
