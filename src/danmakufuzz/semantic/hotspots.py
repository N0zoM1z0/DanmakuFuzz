from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from ..repo import ARTIFACTS_DIR, ensure_directory


def _default_artifact_dir() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ARTIFACTS_DIR / "semantic-hotspots" / stamp


def _site_key(path_info: object) -> tuple[int | None, int | None]:
    if not isinstance(path_info, dict):
        return None, None
    sub_index = path_info.get("sub_index")
    instruction_index = path_info.get("instruction_index")
    return (
        sub_index if isinstance(sub_index, int) else None,
        instruction_index if isinstance(instruction_index, int) else None,
    )


def _family_name(data: dict[str, object]) -> str:
    mutation_metadata = data.get("mutation_metadata")
    if isinstance(mutation_metadata, dict):
        family = mutation_metadata.get("family")
        if isinstance(family, str) and family:
            return family
    mutant_name = data.get("mutant_name")
    if isinstance(mutant_name, str):
        if "-sampled-" in mutant_name:
            return mutant_name.split("-sampled-", 1)[0]
        parts = [part for part in mutant_name.split("-") if part]
        if len(parts) >= 2:
            return "-".join(parts[:2])
        return mutant_name
    return "unknown"


def _mutation_value(data: dict[str, object]) -> int | None:
    mutation_metadata = data.get("mutation_metadata")
    if not isinstance(mutation_metadata, dict):
        return None
    value = mutation_metadata.get("value")
    return value if isinstance(value, int) else None


def _finding_kinds(data: dict[str, object]) -> tuple[str, ...]:
    findings = data.get("findings")
    if not isinstance(findings, list):
        return ()
    kinds: list[str] = []
    seen: set[str] = set()
    for entry in findings:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if not isinstance(kind, str) or kind in seen:
            continue
        seen.add(kind)
        kinds.append(kind)
    return tuple(kinds)


def _load_result(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"semantic hotspot input is not an object: {path}")
    return value


def _result_paths_from_summary_jsonl(path: Path) -> list[Path]:
    discovered: list[Path] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"summary.jsonl entry is not an object: {path}:{line_number}")
            case_name = value.get("case_name")
            if not isinstance(case_name, str):
                raise ValueError(f"summary.jsonl entry is missing case_name: {path}:{line_number}")
            result_path = (path.parent / case_name / "result.json").resolve()
            if not result_path.is_file():
                raise FileNotFoundError(f"summary.jsonl entry points to a missing result.json: {result_path}")
            discovered.append(result_path)
    return discovered


def _discover_results(inputs: list[Path]) -> list[Path]:
    discovered: list[Path] = []
    for item in inputs:
        resolved = item.resolve()
        if resolved.is_file():
            if resolved.name == "result.json":
                discovered.append(resolved)
                continue
            if resolved.name == "summary.jsonl":
                discovered.extend(_result_paths_from_summary_jsonl(resolved))
                continue
            if resolved.name == "campaign.json":
                campaign = _load_result(resolved)
                summary_path = campaign.get("summary")
                if not isinstance(summary_path, str):
                    raise ValueError(f"campaign.json is missing summary path: {resolved}")
                discovered.extend(_result_paths_from_summary_jsonl(Path(summary_path).resolve()))
                continue
            raise ValueError(f"unsupported semantic hotspot input file: {resolved}")
        if resolved.is_dir():
            discovered.extend(sorted(resolved.rglob("result.json")))
            continue
        raise FileNotFoundError(f"semantic hotspot input does not exist: {resolved}")
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in discovered:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


@dataclass
class HotspotAccumulator:
    stage: int | None
    seed_name: str | None
    family: str
    sub_index: int | None
    instruction_index: int | None
    total_cases: int = 0
    interesting_cases: int = 0
    total_values: list[int] | None = None
    interesting_values: list[int] | None = None
    finding_kinds: Counter[str] | None = None
    representative_results: list[str] | None = None

    def __post_init__(self) -> None:
        self.total_values = []
        self.interesting_values = []
        self.finding_kinds = Counter()
        self.representative_results = []

    def add(self, data: dict[str, object], *, result_path: Path) -> None:
        self.total_cases += 1
        value = _mutation_value(data)
        if value is not None:
            self.total_values.append(value)
        interesting = bool(data.get("interesting"))
        if interesting:
            self.interesting_cases += 1
            if value is not None:
                self.interesting_values.append(value)
            for kind in _finding_kinds(data):
                self.finding_kinds[kind] += 1
            if len(self.representative_results) < 8:
                self.representative_results.append(str(result_path.resolve()))

    def to_dict(self) -> dict[str, object]:
        interesting_ratio = (
            float(self.interesting_cases) / float(self.total_cases) if self.total_cases else 0.0
        )
        return {
            "stage": self.stage,
            "seed_name": self.seed_name,
            "family": self.family,
            "path": {
                "sub_index": self.sub_index,
                "instruction_index": self.instruction_index,
            },
            "total_cases": self.total_cases,
            "interesting_cases": self.interesting_cases,
            "interesting_ratio": interesting_ratio,
            "values_total": sorted(self.total_values),
            "values_interesting": sorted(self.interesting_values),
            "finding_kinds": dict(self.finding_kinds.most_common()),
            "representative_results": list(self.representative_results),
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize exploration hotspots by ECL site and sampled value basin."
    )
    parser.add_argument("input", nargs="+", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--min-interesting", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result_paths = _discover_results(args.input)
    artifact_dir = (args.artifact_dir or _default_artifact_dir()).resolve()
    ensure_directory(artifact_dir)

    hotspots: dict[tuple[object, ...], HotspotAccumulator] = {}
    totals = {"results": 0, "interesting": 0, "hotspots": 0}
    for result_path in result_paths:
        data = _load_result(result_path)
        totals["results"] += 1
        if bool(data.get("interesting")):
            totals["interesting"] += 1
        sub_index, instruction_index = _site_key(data.get("path"))
        family = _family_name(data)
        key = (
            data.get("stage") if isinstance(data.get("stage"), int) else None,
            data.get("seed_name") if isinstance(data.get("seed_name"), str) else None,
            family,
            sub_index,
            instruction_index,
        )
        accumulator = hotspots.get(key)
        if accumulator is None:
            accumulator = HotspotAccumulator(
                stage=key[0],
                seed_name=key[1],
                family=family,
                sub_index=sub_index,
                instruction_index=instruction_index,
            )
            hotspots[key] = accumulator
        accumulator.add(data, result_path=result_path)

    rows = [
        accumulator.to_dict()
        for accumulator in hotspots.values()
        if accumulator.interesting_cases >= args.min_interesting
    ]
    rows.sort(
        key=lambda row: (
            -int(row["interesting_cases"]),
            -float(row["interesting_ratio"]),
            -int(row["total_cases"]),
            int(row["path"]["sub_index"]) if isinstance(row["path"]["sub_index"], int) else 2**31 - 1,
            int(row["path"]["instruction_index"]) if isinstance(row["path"]["instruction_index"], int) else 2**31 - 1,
            str(row["family"]),
        )
    )
    limited_rows = rows[: args.limit]
    totals["hotspots"] = len(rows)

    summary = {
        "artifact_dir": str(artifact_dir),
        "inputs": [str(path.resolve()) for path in args.input],
        "totals": totals,
        "rows": limited_rows,
    }
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
