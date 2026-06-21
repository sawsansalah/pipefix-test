"""
Matches raw pipeline log text against the signature library to produce
a fast heuristic pre-classification: which stage(s) failed, in which
language(s), with what failure type, before Claude ever sees the logs.

This narrows Claude's job to root-causing and fixing, rather than also
having to figure out "what kind of failure is this" from scratch.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SIGNATURES_PATH = Path(__file__).parent / "signatures.yaml"


@dataclass
class Match:
    stage: str
    language: str
    failure_type: str
    hint: str
    matched_line: str


@dataclass
class ClassificationResult:
    matches: list[Match] = field(default_factory=list)

    @property
    def stages(self) -> list[str]:
        return sorted({m.stage for m in self.matches})

    @property
    def failure_types(self) -> list[str]:
        return sorted({m.failure_type for m in self.matches})

    @property
    def languages(self) -> list[str]:
        return sorted({m.language for m in self.matches if m.language != "generic"})


def load_signatures() -> list[dict]:
    with open(SIGNATURES_PATH) as f:
        data = yaml.safe_load(f)
    return data["signatures"]


def classify(log_text: str) -> ClassificationResult:
    signatures = load_signatures()
    compiled = [(re.compile(sig["pattern"], re.IGNORECASE), sig) for sig in signatures]

    result = ClassificationResult()
    seen = set()

    for line in log_text.splitlines():
        for pattern, sig in compiled:
            if pattern.search(line):
                key = (sig["stage"], sig["language"], sig["failure_type"])
                if key in seen:
                    continue
                seen.add(key)
                result.matches.append(
                    Match(
                        stage=sig["stage"],
                        language=sig["language"],
                        failure_type=sig["failure_type"],
                        hint=sig["hint"],
                        matched_line=line.strip()[:300],
                    )
                )

    return result
