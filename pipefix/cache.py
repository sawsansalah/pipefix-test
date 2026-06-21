"""
Caches Claude's analysis by a hash of the failure signature, so a repeated
failure (flaky test, same lint error re-introduced, persistent dependency
issue) doesn't trigger another paid API call.

This is a simple file-based cache, fine for a single-repo demo or a
single self-hosted runner with a persistent disk. At real scale, swap
the backend for Redis/a KV store — the get/set interface below is the
seam to do that without touching callers.

IMPORTANT for CI usage: GitHub Actions / GitLab CI runners are normally
ephemeral, so this cache directory needs to be restored/saved across runs
explicitly (e.g. actions/cache on GitHub, cache: on GitLab) or it will
silently never hit. See the workflow files for that wiring.
"""

import hashlib
import json
import os
import time

DEFAULT_CACHE_DIR = os.environ.get("PIPEFIX_CACHE_DIR", ".pipefix_cache")
DEFAULT_TTL_SECONDS = int(os.environ.get("PIPEFIX_CACHE_TTL_SECONDS", str(7 * 24 * 3600)))  # 7 days


def compute_failure_hash(classification, extracted_block: str) -> str:
    """
    Hash on the classifier's view of the failure (stage/language/type)
    plus the extracted block, NOT the full raw log — so the cache key is
    stable across re-runs even if timestamps/run IDs differ in the log,
    but still changes if the actual failure content changes.
    """
    signature_parts = sorted(
        f"{m.stage}:{m.language}:{m.failure_type}" for m in classification.matches
    ) if classification and classification.matches else ["unclassified"]

    hasher = hashlib.sha256()
    hasher.update("|".join(signature_parts).encode("utf-8"))
    hasher.update(b"\n---\n")
    hasher.update(extracted_block.encode("utf-8", errors="replace"))
    return hasher.hexdigest()[:32]


def _cache_path(failure_hash: str, cache_dir: str) -> str:
    return os.path.join(cache_dir, f"{failure_hash}.json")


def get(failure_hash: str, cache_dir: str = DEFAULT_CACHE_DIR, ttl_seconds: int = DEFAULT_TTL_SECONDS):
    path = _cache_path(failure_hash, cache_dir)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r") as f:
            entry = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    age = time.time() - entry.get("cached_at", 0)
    if age > ttl_seconds:
        return None  # stale, treat as a miss

    return entry.get("analysis")


def set(failure_hash: str, analysis: dict, cache_dir: str = DEFAULT_CACHE_DIR) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    path = _cache_path(failure_hash, cache_dir)
    entry = {"cached_at": time.time(), "analysis": analysis}
    try:
        with open(path, "w") as f:
            json.dump(entry, f)
    except OSError as e:
        print(f"[pipefix] Warning: failed to write cache entry: {e}")
