"""
Pipefix — CLI entrypoint.

Usage:
    python -m pipefix.main analyze --logs-dir ./logs --platform auto --post

    --platform: github | gitlab | auto (auto-detects from env vars)
    --post:     actually post the comment to the PR/MR (requires token env vars)
                if omitted, just prints the report to stdout
    --logs-dir: directory containing one or more *.log files to analyze together
    --log-file: a single log file (alternative to --logs-dir)
    --repo-root: path to repo root, used for language detection (default: ".")
"""

import argparse
import glob
import os
import sys

from pipefix import cache
from pipefix.adapters import github_adapter, gitlab_adapter
from pipefix.analyzer import analyze, estimate_cost
from pipefix.detection.classifier import classify
from pipefix.detection.language_detector import detect_languages
from pipefix.extract import extract_failure_block
from pipefix.formatter import format_report
from pipefix.redact import redact


def collect_logs(logs_dir: str | None, log_file: str | None) -> str:
    if log_file:
        with open(log_file, "r", errors="replace") as f:
            return f.read()

    if logs_dir:
        chunks = []
        for path in sorted(glob.glob(os.path.join(logs_dir, "*.log"))):
            stage_name = os.path.splitext(os.path.basename(path))[0]
            with open(path, "r", errors="replace") as f:
                content = f.read()
            chunks.append(f"=== {stage_name} ===\n{content}")
        if not chunks:
            print(f"[pipefix] No .log files found in {logs_dir}", file=sys.stderr)
            sys.exit(1)
        return "\n\n".join(chunks)

    print("[pipefix] Must provide --logs-dir or --log-file", file=sys.stderr)
    sys.exit(1)


def detect_platform(explicit: str) -> str:
    if explicit != "auto":
        return explicit
    if github_adapter.is_active():
        return "github"
    if gitlab_adapter.is_active():
        return "gitlab"
    return "none"


def main():
    parser = argparse.ArgumentParser(prog="pipefix")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze_cmd = sub.add_parser("analyze", help="Analyze pipeline failure logs")
    analyze_cmd.add_argument("--logs-dir", default=None)
    analyze_cmd.add_argument("--log-file", default=None)
    analyze_cmd.add_argument("--repo-root", default=".")
    analyze_cmd.add_argument("--platform", default="auto", choices=["auto", "github", "gitlab", "none"])
    analyze_cmd.add_argument("--post", action="store_true", help="Post result as PR/MR comment")
    analyze_cmd.add_argument("--out", default=None, help="Optional path to write the markdown report")
    analyze_cmd.add_argument("--no-cache", action="store_true", help="Skip the failure-signature cache, always call the analysis engine")
    analyze_cmd.add_argument("--cache-dir", default=None, help="Override cache directory (default: .pipefix_cache or PIPEFIX_CACHE_DIR env var)")
    analyze_cmd.add_argument("--cost-estimate", action="store_true", help="Print real token usage and dollar cost for this run")

    args = parser.parse_args()

    if args.command == "analyze":
        log_text = collect_logs(args.logs_dir, args.log_file)
        log_text = redact(log_text)  # scrub likely secrets before any external use
        languages = detect_languages(args.repo_root)
        classification = classify(log_text)

        print(f"[pipefix] Detected repo languages: {languages}")
        print(f"[pipefix] Heuristic stages matched: {classification.stages or 'none'}")

        # Extract just the relevant failure context instead of sending the
        # whole log — this is the main token/cost reduction lever.
        focused_block = extract_failure_block(log_text, classification)
        print(f"[pipefix] Extracted failure block: {len(focused_block)} chars "
              f"(from {len(log_text)} chars of raw log)")

        cache_dir = args.cache_dir or cache.DEFAULT_CACHE_DIR
        failure_hash = cache.compute_failure_hash(classification, focused_block)

        analysis = None
        cache_hit = False
        if not args.no_cache:
            cached_analysis = cache.get(failure_hash, cache_dir=cache_dir)
            if cached_analysis is not None:
                print(f"[pipefix] Cache hit ({failure_hash}) — skipping the analysis engine call")
                analysis = dict(cached_analysis)
                analysis["cached"] = True
                cache_hit = True

        if analysis is None:
            print("[pipefix] Cache miss — calling analysis engine...")
            analysis = analyze(focused_block, classification)
            analysis["cached"] = False
            if not args.no_cache:
                cache.set(failure_hash, analysis, cache_dir=cache_dir)

        if args.cost_estimate:
            usage = analysis.get("_usage")
            cost = estimate_cost(usage)
            if cache_hit:
                # No API call made this run. Show what it would have cost
                # originally, for context, but actual spend this run is $0.
                original_cost = estimate_cost(usage) if usage else None
                if original_cost:
                    print(
                        f"[pipefix] Cost this run: $0.000000 (cache hit, no API call). "
                        f"Original call when first cached: {original_cost['input_tokens']} in / "
                        f"{original_cost['output_tokens']} out tokens, ${original_cost['total_cost']:.6f}"
                    )
                else:
                    print("[pipefix] Cost this run: $0.000000 (cache hit, no API call)")
            elif cost is None:
                print("[pipefix] Cost this run: $0.000000 (offline mode, no API call was made)")
            else:
                print(
                    f"[pipefix] Token usage — input: {cost['input_tokens']} "
                    f"(${cost['input_cost']:.6f}), output: {cost['output_tokens']} "
                    f"(${cost['output_cost']:.6f})"
                )
                print(f"[pipefix] Total cost this run: ${cost['total_cost']:.6f}")

        platform = detect_platform(args.platform)
        commit_sha = ""

        if platform == "github":
            ctx = github_adapter.get_context()
            commit_sha = ctx.get("commit_sha", "")
            if ctx.get("is_fork_pr") and args.post:
                print(
                    "[pipefix] Refusing to post: this is a fork-originated PR. "
                    "GitHub already withholds secrets from fork PR runs, but we also "
                    "explicitly decline to post as a defense-in-depth measure. "
                    "Printing report instead."
                )
                args.post = False
        elif platform == "gitlab":
            ctx = gitlab_adapter.get_context()
            commit_sha = ctx.get("commit_sha", "")
        else:
            ctx = {}

        report = format_report(classification, analysis, commit_sha=commit_sha)

        print("\n" + report + "\n")

        if args.out:
            with open(args.out, "w") as f:
                f.write(report)
            print(f"[pipefix] Report written to {args.out}")

        if args.post:
            if platform == "github":
                github_adapter.post_comment(ctx, report)
            elif platform == "gitlab":
                gitlab_adapter.post_comment(ctx, report)
            else:
                print("[pipefix] --post given but no platform detected; skipping post.")


if __name__ == "__main__":
    main()
