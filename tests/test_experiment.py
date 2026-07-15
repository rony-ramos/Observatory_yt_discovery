from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from discovery.experiment import KeywordExperimentSuite, run_dictionary_experiment
from discovery.planner import plan_queries


class KeywordExperimentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.suite = KeywordExperimentSuite.load()

    def test_suite_builds_five_versioned_profiles(self) -> None:
        versions = {
            profile_id: self.suite.build_dictionary(profile_id).version
            for profile_id in self.suite.profiles
        }

        self.assertEqual(
            {
                "baseline": "1.0.0",
                "natural": "1.1.0",
                "regional": "1.2.0",
                "local_context": "1.3.0",
                "combined": "1.4.0",
            },
            versions,
        )

    def test_local_context_excludes_portuguese_terms(self) -> None:
        dictionary = self.suite.build_dictionary("local_context")
        argentina = dictionary.iter_variants(
            country="AR",
            indicators=["ingreso"],
        )
        mexico = dictionary.iter_variants(
            country="MX",
            indicators=["ingreso"],
        )

        self.assertFalse(any(item.term_id.endswith(".portugues") for item in argentina))
        self.assertFalse(any(item.term_id.endswith(".portugues") for item in mexico))

    def test_combined_profile_generates_curated_combinations(self) -> None:
        dictionary = self.suite.build_dictionary("combined")
        queries = plan_queries(
            dictionary,
            institution="Universidad Nacional de Rosario",
            aliases=["UNR"],
            country="AR",
            indicators=dictionary.indicator_ids,
            variants_per_term=2,
            max_queries=84,
            balance_by="term",
        )
        combinations = [query for query in queries if query.query_kind == "combination"]

        self.assertEqual(84, len(queries))
        self.assertGreater(len(combinations), 0)
        self.assertTrue(all(query.combination_id for query in combinations))
        self.assertTrue(all(len(query.combines) >= 2 for query in combinations))
        self.assertEqual(5, len({query.combination_id for query in combinations}))

    def test_expanded_scenario_uses_larger_query_budget(self) -> None:
        dictionary = self.suite.build_dictionary("combined")
        controlled = self.suite.get_scenario("controlled")
        expanded = self.suite.get_scenario("expanded")
        controlled_queries = plan_queries(
            dictionary,
            institution="Universidad Nacional de Rosario",
            aliases=["UNR"],
            country="AR",
            indicators=dictionary.indicator_ids,
            variants_per_term=controlled.variants_per_term,
            max_queries=controlled.max_queries,
            balance_by=controlled.balance_by,
        )
        expanded_queries = plan_queries(
            dictionary,
            institution="Universidad Nacional de Rosario",
            aliases=["UNR"],
            country="AR",
            indicators=dictionary.indicator_ids,
            variants_per_term=expanded.variants_per_term,
            max_queries=expanded.max_queries,
            balance_by=expanded.balance_by,
        )

        self.assertEqual(84, len(controlled_queries))
        self.assertEqual(128, len(expanded_queries))
        self.assertGreater(
            sum(query.query_kind == "combination" for query in expanded_queries),
            sum(query.query_kind == "combination" for query in controlled_queries),
        )

    def test_dry_experiment_writes_comparable_summary_and_traceability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            experiment_dir = run_dictionary_experiment(
                suite=self.suite,
                scenario_id="controlled",
                institution="Universidad Nacional de Rosario",
                aliases=["UNR"],
                country="AR",
                output_root=Path(temporary_directory),
                execute=False,
            )

            manifest = json.loads(
                (experiment_dir / "experiment.json").read_text(encoding="utf-8")
            )
            with (experiment_dir / "summary.csv").open(
                encoding="utf-8-sig", newline=""
            ) as source:
                summary = {row["profile_id"]: row for row in csv.DictReader(source)}

            self.assertEqual("planned", manifest["status"])
            self.assertEqual(5, len(manifest["runs"]))
            self.assertEqual(set(self.suite.profiles), set(summary))
            self.assertTrue(all(row["query_count"] == "84" for row in summary.values()))
            self.assertEqual("0", summary["baseline"]["combination_queries"])
            self.assertGreater(int(summary["combined"]["combination_queries"]), 0)
            self.assertEqual("1260", summary["combined"]["planned_results"])

            combined_run = experiment_dir / summary["combined"]["run_dir"]
            run_manifest = json.loads(
                (combined_run / "run.json").read_text(encoding="utf-8")
            )
            with (combined_run / "queries.csv").open(
                encoding="utf-8-sig", newline=""
            ) as source:
                query_rows = list(csv.DictReader(source))

            self.assertEqual("combined", run_manifest["experiment_profile"])
            self.assertTrue(any(row["query_kind"] == "combination" for row in query_rows))
            self.assertTrue(any(row["combines"] for row in query_rows))

    def test_expanded_scenario_requires_explicit_winner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "requiere seleccionar"):
                run_dictionary_experiment(
                    suite=self.suite,
                    scenario_id="expanded",
                    institution="Universidad Nacional de Rosario",
                    aliases=["UNR"],
                    country="AR",
                    output_root=Path(temporary_directory),
                    execute=False,
                )


if __name__ == "__main__":
    unittest.main()
