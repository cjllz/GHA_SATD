"""4. Randomly sample keyword-nonhit comments with finite-population correction."""

import argparse
import csv
import gzip
import json
import math
import random
from pathlib import Path


DEFAULT_SEED = 20261116


def sample_size(population_size, confidence_z=1.96, margin=0.05, proportion=0.5):
    """Return the ceiling sample size for a finite population."""
    numerator = population_size * confidence_z**2 * proportion * (1 - proportion)
    denominator = margin**2 * (population_size - 1) + confidence_z**2 * proportion * (1 - proportion)
    return math.ceil(numerator / denominator)


def load_population(path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        rows = json.load(stream)
    required = {"repository", "uid", "satd_comment_id"}
    if not isinstance(rows, list) or any(not required <= row.keys() for row in rows):
        raise ValueError("Input must be a JSON list containing repository, uid and satd_comment_id")
    return rows


def stable_key(row):
    return row["repository"], row["uid"], row["satd_comment_id"]


def draw_sample(population, seed):
    ordered = sorted(population, key=stable_key)
    if len({stable_key(row) for row in ordered}) != len(ordered):
        raise ValueError("Population contains duplicate records")
    size = sample_size(len(ordered))
    return random.Random(seed).sample(ordered, size)


def write_sample(path, rows):
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["sample_index", "repository", "uid", "satd_comment_id"]
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, row in enumerate(rows, 1):
            writer.writerow({"sample_index": index, **{field: row[field] for field in fields[1:]}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--expected-population", type=int, default=33003)
    args = parser.parse_args()

    population = load_population(args.input)
    if len(population) != args.expected_population:
        raise ValueError(
            f"Expected {args.expected_population:,} records, found {len(population):,}"
        )
    sample = draw_sample(population, args.seed)
    write_sample(args.output, sample)
    print(json.dumps({
        "population": len(population),
        "confidence_level": 0.95,
        "margin_of_error": 0.05,
        "assumed_proportion": 0.5,
        "sample_size": len(sample),
        "seed": args.seed,
        "output": str(args.output.resolve()),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
