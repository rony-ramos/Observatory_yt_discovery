from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from discovery.experiment import DEFAULT_SUITE, KeywordExperimentSuite
from validate_dictionary import ValidationError, validate_dictionary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida todos los perfiles derivados de una suite experimental."
    )
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    args = parser.parse_args()

    try:
        suite = KeywordExperimentSuite.load(args.suite)
        for profile_id in suite.profiles:
            dictionary = suite.build_dictionary(profile_id)
            counts = validate_dictionary(dictionary.data)
            print(
                f"{profile_id}: v{dictionary.version}, {counts['terms']} terminos, "
                f"{counts['rules']} reglas."
            )
    except (KeyError, OSError, ValueError, ValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Suite valida: {suite.id}, {len(suite.profiles)} perfiles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
