from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
from typing import Iterable

from .dictionary import KeywordDictionary, KeywordVariant, normalize_text


@dataclass(frozen=True)
class SearchQuery:
    query_id: str
    query: str
    institution_alias: str
    country: str
    indicator: str
    concept: str
    term_id: str
    term: str
    locale: str
    intents: tuple[str, ...]
    score: float
    dictionary_version: str

    def as_row(self) -> dict[str, str | float]:
        return {
            "query_id": self.query_id,
            "query": self.query,
            "institution_alias": self.institution_alias,
            "country": self.country,
            "indicator": self.indicator,
            "concept": self.concept,
            "term_id": self.term_id,
            "term": self.term,
            "locale": self.locale,
            "intents": ";".join(self.intents),
            "score": round(self.score, 3),
            "dictionary_version": self.dictionary_version,
        }


def _unique_aliases(institution: str, aliases: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for alias in (institution, *aliases):
        cleaned = " ".join(alias.split())
        normalized = normalize_text(cleaned)
        if cleaned and normalized not in seen:
            seen.add(normalized)
            result.append(cleaned)
    return result


def _select_variants_per_term(
    variants: list[KeywordVariant], limit: int
) -> list[KeywordVariant]:
    grouped: dict[str, list[KeywordVariant]] = defaultdict(list)
    for variant in variants:
        grouped[variant.term_id].append(variant)

    selected: list[KeywordVariant] = []
    for term_variants in grouped.values():
        ordered = sorted(
            term_variants,
            key=lambda item: (
                item.locale == "global",
                -item.weight,
                len(item.phrase),
                normalize_text(item.phrase),
            ),
        )
        selected.extend(ordered[:limit])
    return selected


def _round_robin(candidates: list[SearchQuery], limit: int) -> list[SearchQuery]:
    groups: dict[tuple[str, str], deque[SearchQuery]] = {}
    for candidate in sorted(
        candidates,
        key=lambda item: (-item.score, item.indicator, item.concept, item.query),
    ):
        groups.setdefault((candidate.indicator, candidate.concept), deque()).append(candidate)

    selected: list[SearchQuery] = []
    while groups and len(selected) < limit:
        for key in list(groups):
            queue = groups[key]
            if queue and len(selected) < limit:
                selected.append(queue.popleft())
            if not queue:
                del groups[key]
    return selected


def plan_queries(
    dictionary: KeywordDictionary,
    *,
    institution: str,
    aliases: Iterable[str],
    country: str,
    indicators: Iterable[str],
    concepts: Iterable[str] | None = None,
    intents: Iterable[str] | None = None,
    statuses: Iterable[str] = ("seed", "validated"),
    variants_per_term: int = 2,
    max_queries: int = 24,
) -> list[SearchQuery]:
    if variants_per_term < 1:
        raise ValueError("variants_per_term debe ser mayor que cero.")
    if max_queries < 1:
        raise ValueError("max_queries debe ser mayor que cero.")

    institution_aliases = _unique_aliases(institution, aliases)
    if not institution_aliases:
        raise ValueError("Se requiere al menos un nombre de institucion.")

    variants = dictionary.iter_variants(
        country=country,
        indicators=indicators,
        concepts=concepts,
        intents=intents,
        statuses=statuses,
    )
    selected_variants = _select_variants_per_term(variants, variants_per_term)

    candidates: list[SearchQuery] = []
    seen_queries: set[str] = set()
    for variant in selected_variants:
        for alias_position, alias in enumerate(institution_aliases):
            query = f"{alias} {variant.phrase}"
            normalized = normalize_text(query)
            if normalized in seen_queries:
                continue
            seen_queries.add(normalized)

            locale_bonus = 0.15 if variant.locale == country else 0.0
            primary_alias_bonus = 0.05 if alias_position == 0 else 0.0
            candidates.append(
                SearchQuery(
                    query_id="",
                    query=query,
                    institution_alias=alias,
                    country=country,
                    indicator=variant.indicator,
                    concept=variant.concept,
                    term_id=variant.term_id,
                    term=variant.phrase,
                    locale=variant.locale,
                    intents=variant.intents,
                    score=variant.weight + locale_bonus + primary_alias_bonus,
                    dictionary_version=dictionary.version,
                )
            )

    selected = _round_robin(candidates, max_queries)
    return [replace(item, query_id=f"q{index:04d}") for index, item in enumerate(selected, 1)]

