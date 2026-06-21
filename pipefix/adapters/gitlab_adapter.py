"""
GitLab CI adapter. Reads standard CI_* env vars that GitLab CI sets
automatically, and posts the report as a merge request note via the
REST API using a CI_JOB_TOKEN or GITLAB_TOKEN.
"""

import json
import os
import urllib.parse
import urllib.request


def is_active() -> bool:
    return os.environ.get("GITLAB_CI") == "true"


def get_context() -> dict:
    project_id = os.environ.get("CI_PROJECT_ID", "")
    sha = os.environ.get("CI_COMMIT_SHA", "")
    mr_iid = os.environ.get("CI_MERGE_REQUEST_IID")
    api_url = os.environ.get("CI_API_V4_URL", "https://gitlab.com/api/v4")

    return {
        "platform": "gitlab",
        "project_id": project_id,
        "commit_sha": sha,
        "mr_iid": mr_iid,
        "api_url": api_url,
    }


def post_comment(context: dict, body: str) -> None:
    project_id = context["project_id"]
    mr_iid = context.get("mr_iid")
    api_url = context["api_url"]

    token = os.environ.get("GITLAB_TOKEN") or os.environ.get("CI_JOB_TOKEN")

    if not token:
        print("[gitlab_adapter] No token set (GITLAB_TOKEN/CI_JOB_TOKEN), printing report instead:\n")
        print(body)
        return

    if not mr_iid:
        print("[gitlab_adapter] No MR IID found (not an MR pipeline), printing report instead:\n")
        print(body)
        return

    encoded_project = urllib.parse.quote(str(project_id), safe="")
    url = f"{api_url}/projects/{encoded_project}/merge_requests/{mr_iid}/notes"
    data = json.dumps({"body": body}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"[gitlab_adapter] Posted note, status {resp.status}")
    except Exception as e:
        print(f"[gitlab_adapter] Failed to post note: {e}")
        print(body)
