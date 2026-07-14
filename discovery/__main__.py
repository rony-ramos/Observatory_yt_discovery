from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .dictionary import KeywordDictionary, PROJECT_ROOT
from .institutions import InstitutionRegistry
from .pipeline import run_search_pipeline
from .planner import plan_queries
from .yt_search import SearchDependencyError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Planifica y ejecuta busquedas planas de videos en YouTube."
    )
    parser.add_argument(
        "--institution-id",
        help="ID del padron de instituciones. Si se usa, carga nombre, pais, aliases y canales.",
    )
    parser.add_argument("--institutions", help="Ruta a una version especifica del padron.")
    parser.add_argument("--institution", help="Nombre oficial de la institucion.")
    parser.add_argument(
        "--alias",
        action="append",
        default=[],
        help="Alias adicional. Puede repetirse.",
    )
    parser.add_argument("--country", help="Codigo ISO del pais, por ejemplo AR.")
    parser.add_argument(
        "--indicator",
        action="append",
        required=True,
        help="Indicador a buscar. Puede repetirse.",
    )
    parser.add_argument("--concept", action="append", help="Concepto opcional.")
    parser.add_argument("--intent", action="append", help="Intencion opcional.")
    parser.add_argument(
        "--status",
        nargs="+",
        default=["seed", "validated"],
        help="Estados de keywords habilitados.",
    )
    parser.add_argument("--dictionary", help="Ruta a una version especifica del diccionario.")
    parser.add_argument("--variants-per-term", type=int, default=2)
    parser.add_argument("--max-queries", type=int, default=24)
    parser.add_argument("--results-per-query", type=int, default=20)
    parser.add_argument("--min-sleep", type=float, default=5.0)
    parser.add_argument("--max-sleep", type=float, default=10.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument(
        "--published-after",
        type=date.fromisoformat,
        default=date(2021, 12, 31),
        help="Prioriza fechas posteriores a YYYY-MM-DD. Default: 2021-12-31.",
    )
    parser.add_argument(
        "--date-policy",
        choices=("prefer", "strict"),
        default="prefer",
        help="prefer ordena primero los recientes; strict excluye los demas.",
    )
    parser.add_argument(
        "--institution-policy",
        choices=("strict", "prefer", "off"),
        default="strict",
        help="strict excluye videos que no mencionan la institucion en sus metadatos.",
    )
    parser.add_argument("--metadata-min-sleep", type=float, default=2.5)
    parser.add_argument("--metadata-max-sleep", type=float, default=5.0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "runs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Genera el plan sin conectarse a YouTube.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        registry = None
        registry_institution = None
        if args.institution_id:
            registry = InstitutionRegistry.load(args.institutions)
            registry_institution = registry.get(args.institution_id)
            args.institution = registry_institution.name
            args.alias = list(registry_institution.aliases) + list(args.alias)
            args.country = registry_institution.country

        if not args.institution:
            raise ValueError("Debes enviar --institution o --institution-id.")
        if not args.country:
            raise ValueError("Debes enviar --country o usar --institution-id.")

        dictionary = KeywordDictionary.load(args.dictionary)
        queries = plan_queries(
            dictionary,
            institution=args.institution,
            aliases=args.alias,
            country=args.country.upper(),
            indicators=args.indicator,
            concepts=args.concept,
            intents=args.intent,
            statuses=args.status,
            variants_per_term=args.variants_per_term,
            max_queries=args.max_queries,
        )
        if not queries:
            raise ValueError("No se generaron consultas con los filtros elegidos.")

        print(
            f"Plan: {len(queries)} consultas, diccionario v{dictionary.version}, "
            f"pais {args.country.upper()}."
        )
        if args.dry_run:
            for query in queries:
                print(f"  {query.query_id} [{query.concept}] {query.query}")

        run_dir = run_search_pipeline(
            queries=queries,
            institution=args.institution,
            aliases=args.alias,
            country=args.country.upper(),
            results_per_query=args.results_per_query,
            output_root=args.output_dir,
            dry_run=args.dry_run,
            min_sleep=args.min_sleep,
            max_sleep=args.max_sleep,
            retries=args.retries,
            published_after=args.published_after,
            date_policy=args.date_policy,
            institution_policy=args.institution_policy,
            metadata_min_sleep=args.metadata_min_sleep,
            metadata_max_sleep=args.metadata_max_sleep,
            institution_registry_version=registry.version if registry else None,
            institution_id=registry_institution.id if registry_institution else None,
            institution_eligibility=(
                {
                    "licensed": registry_institution.licensed,
                    "qs_ranked": registry_institution.qs_ranked,
                    "verification_status": registry_institution.verification_status,
                }
                if registry_institution
                else None
            ),
            official_channel_ids=(
                list(registry_institution.official_channel_ids)
                if registry_institution
                else None
            ),
            official_channel_names=(
                list(registry_institution.official_channel_names)
                if registry_institution
                else None
            ),
        )
    except (ValueError, KeyError, OSError, SearchDependencyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Corrida guardada en: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
