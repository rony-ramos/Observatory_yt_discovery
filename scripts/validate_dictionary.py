from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "config" / "keywords" / "manifest.yaml"
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
ID_PATTERN = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)*$")


class ValidationError(Exception):
    pass


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as source:
            data = yaml.safe_load(source)
    except FileNotFoundError as exc:
        raise ValidationError(f"No existe el archivo: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValidationError(f"YAML invalido en {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValidationError(f"La raiz de {path} debe ser un objeto YAML.")
    return data


def require_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValidationError(f"'{key}' debe ser un objeto.")
    return value


def require_list(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        raise ValidationError(f"'{key}' debe ser una lista no vacia.")
    return value


def unique_values(values: list[str], label: str) -> set[str]:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValidationError(f"{label} duplicados: {', '.join(duplicates)}")
    return set(values)


def validate_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValidationError(f"{label} invalido: {value!r}")
    return value


def validate_manifest(manifest: dict[str, Any], dictionary_path: Path) -> None:
    active_version = manifest.get("active_version")
    if not isinstance(active_version, str) or not SEMVER_PATTERN.fullmatch(active_version):
        raise ValidationError("manifest.active_version debe usar versionado semantico.")

    versions = require_list(manifest, "versions")
    registered = {
        item.get("version"): item.get("file")
        for item in versions
        if isinstance(item, dict)
    }
    if active_version not in registered:
        raise ValidationError("La version activa no esta registrada en el manifiesto.")
    if dictionary_path.name not in registered.values():
        raise ValidationError(
            f"El archivo {dictionary_path.name} no esta registrado en el manifiesto."
        )


def validate_dictionary(data: dict[str, Any]) -> dict[str, int]:
    if data.get("schema_version") != "1.0":
        raise ValidationError("schema_version debe ser '1.0'.")

    metadata = require_mapping(data, "dictionary")
    version = metadata.get("version")
    if not isinstance(version, str) or not SEMVER_PATTERN.fullmatch(version):
        raise ValidationError("dictionary.version debe usar versionado semantico.")

    countries = require_list(data, "countries")
    country_codes = unique_values(
        [item.get("code") for item in countries if isinstance(item, dict)],
        "Codigos de pais",
    )
    if len(country_codes) != len(countries):
        raise ValidationError("Cada pais debe ser un objeto con codigo unico.")

    statuses = unique_values(require_list(data, "statuses"), "Estados")
    source_types = unique_values(require_list(data, "source_types"), "Tipos de fuente")

    intent_rows = require_list(data, "intents")
    intent_ids = unique_values(
        [item.get("id") for item in intent_rows if isinstance(item, dict)],
        "Intenciones",
    )
    if len(intent_ids) != len(intent_rows):
        raise ValidationError("Cada intencion debe ser un objeto con id unico.")

    indicators = require_list(data, "indicators")
    indicator_ids: list[str] = []
    concept_to_indicator: dict[str, str] = {}
    for indicator in indicators:
        if not isinstance(indicator, dict):
            raise ValidationError("Cada indicador debe ser un objeto.")
        indicator_id = validate_id(indicator.get("id"), "Id de indicador")
        indicator_ids.append(indicator_id)
        for concept in require_list(indicator, "concepts"):
            if not isinstance(concept, dict):
                raise ValidationError(f"Concepto invalido en {indicator_id}.")
            concept_id = validate_id(concept.get("id"), "Id de concepto")
            if concept_id in concept_to_indicator:
                raise ValidationError(f"Concepto duplicado: {concept_id}")
            concept_to_indicator[concept_id] = indicator_id
    indicator_id_set = unique_values(indicator_ids, "Indicadores")

    provenance_rows = require_list(data, "provenance")
    provenance_ids = unique_values(
        [item.get("id") for item in provenance_rows if isinstance(item, dict)],
        "Fuentes de procedencia",
    )

    terms = require_list(data, "terms")
    term_ids: list[str] = []
    for term in terms:
        if not isinstance(term, dict):
            raise ValidationError("Cada termino debe ser un objeto.")

        term_id = validate_id(term.get("id"), "Id de termino")
        term_ids.append(term_id)
        indicator_id = term.get("indicator")
        concept_id = term.get("concept")

        if indicator_id not in indicator_id_set:
            raise ValidationError(f"{term_id}: indicador desconocido {indicator_id!r}.")
        if concept_to_indicator.get(concept_id) != indicator_id:
            raise ValidationError(
                f"{term_id}: el concepto {concept_id!r} no pertenece a {indicator_id!r}."
            )
        if term.get("status") not in statuses:
            raise ValidationError(f"{term_id}: estado desconocido {term.get('status')!r}.")
        if term.get("provenance") not in provenance_ids:
            raise ValidationError(f"{term_id}: procedencia desconocida.")

        weight = term.get("search_weight")
        if not isinstance(weight, (int, float)) or not 0 <= weight <= 1:
            raise ValidationError(f"{term_id}: search_weight debe estar entre 0 y 1.")

        term_intents = term.get("intents")
        if not isinstance(term_intents, list) or not term_intents:
            raise ValidationError(f"{term_id}: intents debe ser una lista no vacia.")
        unknown_intents = set(term_intents) - intent_ids
        if unknown_intents:
            raise ValidationError(
                f"{term_id}: intenciones desconocidas: {sorted(unknown_intents)}"
            )

        term_sources = term.get("source_types")
        if not isinstance(term_sources, list) or not term_sources:
            raise ValidationError(f"{term_id}: source_types debe ser una lista no vacia.")
        unknown_sources = set(term_sources) - source_types
        if unknown_sources:
            raise ValidationError(
                f"{term_id}: tipos de fuente desconocidos: {sorted(unknown_sources)}"
            )

        variants = term.get("variants")
        if not isinstance(variants, dict) or not variants.get("global"):
            raise ValidationError(f"{term_id}: variants.global debe ser una lista no vacia.")
        unknown_countries = set(variants) - country_codes - {"global"}
        if unknown_countries:
            raise ValidationError(
                f"{term_id}: paises desconocidos: {sorted(unknown_countries)}"
            )
        for locale, values in variants.items():
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                raise ValidationError(
                    f"{term_id}: variantes invalidas para el ambito {locale}."
                )

    term_id_set = unique_values(term_ids, "Terminos")

    rules = require_list(data, "ambiguity_rules")
    rule_ids: list[str] = []
    allowed_actions = {"exclude", "remap", "review"}
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValidationError("Cada regla de ambiguedad debe ser un objeto.")
        rule_id = validate_id(rule.get("id"), "Id de regla")
        rule_ids.append(rule_id)
        references = rule.get("term_ids")
        if not isinstance(references, list) or not references:
            raise ValidationError(f"{rule_id}: term_ids debe ser una lista no vacia.")
        unknown_terms = set(references) - term_id_set
        if unknown_terms:
            raise ValidationError(
                f"{rule_id}: terminos desconocidos: {sorted(unknown_terms)}"
            )
        if rule.get("action") not in allowed_actions:
            raise ValidationError(f"{rule_id}: accion desconocida.")
        if rule.get("action") == "remap":
            target = rule.get("target")
            if not isinstance(target, dict):
                raise ValidationError(f"{rule_id}: remap requiere target.")
            target_indicator = target.get("indicator")
            target_concept = target.get("concept")
            if concept_to_indicator.get(target_concept) != target_indicator:
                raise ValidationError(f"{rule_id}: target no corresponde a la ontologia.")
    unique_values(rule_ids, "Reglas")

    return {
        "countries": len(country_codes),
        "indicators": len(indicator_id_set),
        "concepts": len(concept_to_indicator),
        "terms": len(term_id_set),
        "rules": len(rule_ids),
    }


def resolve_dictionary_path(argument: str | None) -> tuple[Path, dict[str, Any]]:
    manifest = load_yaml(MANIFEST_PATH)
    if argument:
        path = Path(argument)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve(), manifest

    active_version = manifest.get("active_version")
    versions = manifest.get("versions", [])
    active_file = next(
        (
            item.get("file")
            for item in versions
            if isinstance(item, dict) and item.get("version") == active_version
        ),
        None,
    )
    if not active_file:
        raise ValidationError("No se pudo resolver el archivo activo del manifiesto.")
    return (MANIFEST_PATH.parent / active_file).resolve(), manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida el diccionario de keywords.")
    parser.add_argument("dictionary", nargs="?", help="Ruta opcional al YAML a validar.")
    args = parser.parse_args()

    try:
        dictionary_path, manifest = resolve_dictionary_path(args.dictionary)
        validate_manifest(manifest, dictionary_path)
        data = load_yaml(dictionary_path)
        counts = validate_dictionary(data)

        dictionary_version = data["dictionary"]["version"]
        if dictionary_version not in {
            item.get("version")
            for item in manifest["versions"]
            if isinstance(item, dict)
        }:
            raise ValidationError(
                f"La version {dictionary_version} no esta registrada en el manifiesto."
            )

    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        "Diccionario valido: "
        f"v{dictionary_version}, "
        f"{counts['countries']} paises, "
        f"{counts['indicators']} indicadores, "
        f"{counts['concepts']} conceptos, "
        f"{counts['terms']} terminos y "
        f"{counts['rules']} reglas."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
