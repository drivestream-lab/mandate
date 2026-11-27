"""Record a human review decision for a merged pull request (REQ-120).

Run by hand. Appends one JSON line in the ledger entry format (actor, choice, target commit,
version stamp) to the local file given as --output. It never writes into mandate-meta: KD
commits the output to mandate-meta/ledger-import/ separately.

    python scripts/record_review_decision.py --output /tmp/decisions.jsonl \
        --actor nikd10x --choice approved --target-commit <40-hex sha> \
        --pull-request drivestream-lab/mandate#12 --mandate-release 0.1.0 --rules-version v0.5.12
"""

import argparse
import sys
from pathlib import Path

from src.models.review_decision_models import (
    ReviewChoiceType,
    ReviewDecisionEntry,
    ReviewVersionStamp,
)

_FORBIDDEN_OUTPUT_DIR = "mandate-meta"


def output_is_allowed(output: Path) -> bool:
    """False for any path inside a mandate-meta directory."""
    return _FORBIDDEN_OUTPUT_DIR not in output.resolve().parts


def to_json_line(entry: ReviewDecisionEntry) -> str:
    return entry.model_dump_json() + "\n"


def append_decision(entry: ReviewDecisionEntry, output: Path) -> None:
    if not output_is_allowed(output):
        raise ValueError(f"refusing to write inside {_FORBIDDEN_OUTPUT_DIR}: {output}")
    with output.open("a", encoding="utf-8") as handle:
        handle.write(to_json_line(entry))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--choice", type=ReviewChoiceType, choices=list(ReviewChoiceType), required=True)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--pull-request", required=True)
    parser.add_argument("--mandate-release", required=True)
    parser.add_argument("--rules-version", required=True)
    args = parser.parse_args(argv)
    entry = ReviewDecisionEntry(
        actor=args.actor,
        choice=args.choice,
        target_commit=args.target_commit,
        pull_request=args.pull_request,
        version_stamp=ReviewVersionStamp(
            mandate_release=args.mandate_release, rules_version=args.rules_version
        ),
    )
    append_decision(entry, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
