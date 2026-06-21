"""
Detects which languages/ecosystems are present in a repo by checking
for well-known marker files. Used to narrow down which signatures to
prioritize and to give Claude useful context.
"""

import os

MARKERS = {
    "python": ["requirements.txt", "pyproject.toml", "setup.py", "Pipfile"],
    "node": ["package.json", "yarn.lock", "pnpm-lock.yaml"],
    "go": ["go.mod", "go.sum"],
    "rust": ["Cargo.toml"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
}


def detect_languages(repo_root: str = ".") -> list[str]:
    """Walk repo_root (shallow, top 2 levels) looking for marker files."""
    found = set()

    for depth_root, dirs, files in os.walk(repo_root):
        # don't descend into dependency / vcs directories
        dirs[:] = [
            d for d in dirs
            if d not in {".git", "node_modules", "venv", ".venv", "target", "dist", "build"}
        ]
        depth = depth_root[len(repo_root):].count(os.sep)
        if depth > 2:
            dirs[:] = []
            continue

        for lang, markers in MARKERS.items():
            for marker in markers:
                if marker in files:
                    found.add(lang)

    return sorted(found) if found else ["generic"]
