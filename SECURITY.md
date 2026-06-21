# Security Design

Pipefix runs inside CI, has a credential to a third-party LLM API, and
posts content into your PR/MR — three reasons to think carefully about
least privilege. Below is what's implemented and what you still need to
configure yourself.

## Threat model (what this guards against)

1. **A malicious/compromised PR triggers the workflow and tries to exfiltrate secrets.**
   Mitigated by: splitting CI into two jobs so only the analysis job ever sees
   `ANTHROPIC_API_KEY`; the build job that actually runs untrusted PR code never
   has it. Fork PRs additionally get an explicit `is_fork_pr` check that refuses
   to post even if somehow triggered (on top of GitHub's own secret-withholding
   for fork PRs).

2. **Log output accidentally contains a real secret (leaked env var, accidental print)
   and that secret gets sent to a third-party API.**
   Mitigated by: `agent/redact.py` scrubs common secret shapes (cloud keys, GitHub/GitLab
   tokens, Bearer headers, JWTs, private key blocks, generic `key=value` assignments)
   before logs are classified or sent to Claude. This is regex-based and best-effort,
   not a guarantee — don't rely on it as your only control. Best practice: don't `set -x`
   or print secrets to stdout in your actual pipeline steps in the first place.

3. **Log content tries to manipulate the LLM via prompt injection** (e.g. a test name
   or print statement containing "ignore previous instructions...").
   Mitigated by: the system prompt explicitly tells Claude to treat log content as
   data, not instructions, and the agent never executes anything Claude returns —
   output is rendered as a markdown comment only, never as code that runs.

4. **The CI token used to post comments has more access than it needs.**
   Mitigated by: GitHub Actions workflow uses `permissions: {}` at the workflow
   level, with each job opting in to the minimum (`contents: read` for build,
   `pull-requests: write` + `contents: read` for the analysis job only — never
   `contents: write`, `issues: write`, or anything broader).

5. **A compromised GitHub Action in the dependency chain tampers with the workflow.**
   Mitigated by: `actions/checkout` and `actions/setup-python` are pinned to a
   specific commit SHA (not the mutable `v4`/`v5` tag), verified directly against
   GitHub's API at the time this was written. `persist-credentials: false` is set
   on checkout so no token-bearing git config is left on disk for later steps to read.

## What you still need to configure

- **GitHub:** create a `pipefix` Environment (Settings → Environments) and require
  reviewer approval for runs against it, especially for first-time contributors.
  This stops a brand-new PR from silently burning your API budget or probing the
  agent before a maintainer has looked at it.
- **GitHub:** pin `actions/upload-artifact` and `actions/download-artifact` to a
  commit SHA too (left at the `v4` tag in this repo because GitHub's API was
  rate-limiting unauthenticated requests when this was generated — verify and
  pin before production use, or use a tool like `pin-github-action`).
- **GitLab:** mark `ANTHROPIC_API_KEY` and `GITLAB_TOKEN` as both **Protected**
  and **Masked** in Settings → CI/CD → Variables.
- **GitLab:** if you must use a personal/project access token instead of
  `CI_JOB_TOKEN`, scope it to this project only, give it the minimum role that
  can post MR notes (usually Developer, not Maintainer/Owner), restrict its
  scope to `api` only, and set an expiration date.
- **Both platforms:** rotate `ANTHROPIC_API_KEY` periodically and scope it to a
  workspace/project with spend limits if your Anthropic plan supports it.

## What's deliberately NOT sent anywhere

- Raw logs are never included in the posted comment — only Claude's analysis
  (root cause, fixes, prevention tip) is. So even if a secret slipped past
  redaction and reached Claude, it still wouldn't end up reflected back into
  the public PR comment unless Claude's analysis happened to quote it back,
  which the prompt doesn't ask it to do.
- The agent never executes code it didn't write itself — `fixes[].code` from
  Claude's response is rendered as a markdown code block in the comment, never
  run.
