"""
GitHub Actions adapter. Reads standard GITHUB_* env vars that Actions
sets automatically, and posts the report as a PR comment via the
REST API using GITHUB_TOKEN (auto-provided by Actions, no setup needed).
"""

import json
import os
import urllib.request


def is_active() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def get_context() -> dict:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    sha = os.environ.get("GITHUB_SHA", "")
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")

    pr_number = None
    is_fork_pr = False
    if event_path and os.path.exists(event_path):
        with open(event_path) as f:
            event = json.load(f)
        pull_request = event.get("pull_request") or {}
        pr_number = pull_request.get("number")
        head_repo = (pull_request.get("head") or {}).get("repo") or {}
        base_repo = (pull_request.get("base") or {}).get("repo") or {}
        # A PR is fork-originated if the head repo differs from the base repo.
        if head_repo.get("full_name") and base_repo.get("full_name"):
            is_fork_pr = head_repo["full_name"] != base_repo["full_name"]

    return {
        "platform": "github",
        "repo": repo,
        "commit_sha": sha,
        "pr_number": pr_number,
        "is_fork_pr": is_fork_pr,
    }


def post_comment(context: dict, body: str) -> None:
    repo = context["repo"]
    pr_number = context.get("pr_number")
    token = os.environ.get("GITHUB_TOKEN")

    if not token:
        print("[github_adapter] GITHUB_TOKEN not set, printing report instead:\n")
        print(body)
        return

    if not pr_number:
        print("[github_adapter] No PR number found (not a PR event), printing report instead:\n")
        print(body)
        return

    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    data = json.dumps({"body": body}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"[github_adapter] Posted comment, status {resp.status}")
    except Exception as e:
        print(f"[github_adapter] Failed to post comment: {e}")
        print(body)
