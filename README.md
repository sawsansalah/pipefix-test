# 🩺 Pipefix

An AI-powered CI/CD failure analyzer that works across **GitHub Actions** and
**GitLab CI**, and across **multiple languages and pipeline stages** —
install, build, lint, test, security scan, Docker, and deploy.

On a pipeline failure, it:
1. Detects which language(s) the repo uses (Python, Node, Go, Rust, Java — extensible)
2. Runs a fast heuristic classifier against a signature library to identify stage + failure type
3. Extracts just the relevant failure block from the log (cuts tokens sent to Claude by 80-90% on noisy logs)
4. Checks a failure-signature cache — a repeated failure (flaky test, recurring lint error) skips the API call entirely
5. On a cache miss, sends the extracted block + classification to **Claude** for root cause analysis and fix suggestions
6. Posts a structured report as a **PR comment (GitHub)** or **MR note (GitLab)**

If no `ANTHROPIC_API_KEY` is set, it still runs end-to-end using heuristic-only
output — useful for testing the pipeline plumbing without live credentials.

See [SECURITY.md](./SECURITY.md) for the threat model and least-privilege
design decisions (secret redaction, job-splitting so only one job ever touches
the API key, pinned actions, fork-PR handling, prompt-injection guarding).

---

## Architecture

```
GitHub Actions  ──┐
                   ├─► main.py picks the right adapter
GitLab CI       ──┘
                          │
                          ▼
              Language detector (file markers)
                          │
                          ▼
              Signature classifier (signatures.yaml)
                          │
                          ▼
              Failure block extractor (extract.py)
                  — shrinks the log to just the failure context —
                          │
                          ▼
              Cache lookup by failure-signature hash (cache.py)
                  — hit? skip the API call entirely —
                          │
                     (miss) ▼
              Claude analysis (analyzer.py)
                          │
                          ▼
              Markdown formatter (formatter.py)
                          │
                          ▼
              Adapter posts comment:
              - GitHub: PR comment via REST API
              - GitLab: MR note via REST API
```

---

## Quick start (local test, no CI needed)

```bash
pip install -r requirements.txt

# Generate a failing log from the sample Python app
cd sample-apps/python-app
pip install -r requirements.txt
mkdir -p ../../logs
pytest 2>&1 | tee ../../logs/test.log
cd ../..

# Run the agent against it
python -m pipefix.main analyze --logs-dir ./logs --repo-root ./sample-apps/python-app --platform none
```

Set `ANTHROPIC_API_KEY` in your shell first to get real Claude analysis instead
of the offline heuristic fallback.

---

## Using it in GitHub Actions

See `.github/workflows/pipefix.yml`. It's split into two jobs by design:
`ci` (runs untrusted PR code, read-only, never sees the API key) and `pipefix`
(the only job with the secret and the only job with `pull-requests: write`).
Add this repo secret:

| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | from console.anthropic.com |

`GITHUB_TOKEN` is auto-provided by Actions — no setup needed. Consider also
creating a `pipefix` Environment with required reviewers (see SECURITY.md).

## Using it in GitLab CI

See `.gitlab-ci.yml`. Add these CI/CD variables (Settings → CI/CD → Variables):

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | from console.anthropic.com |
| `GITLAB_TOKEN` | a project/personal access token with `api` scope (only needed if `CI_JOB_TOKEN` lacks permission to post notes) |

---

## Cost controls

Two things keep API spend down, both on by default:

- **Failure-block extraction** (`pipefix/extract.py`) — sends Claude only the
  lines around the actual error, not the whole log. On a noisy build this is
  often a 80-90% reduction in input tokens.
- **Failure-signature caching** (`pipefix/cache.py`) — hashes the classified
  failure type + extracted block; a repeated failure (flaky test, the same
  lint error reintroduced) is served from cache instead of calling Claude again.
  The cached/non-cached state is shown in the posted report (💾 badge).

Cache persistence is wired into both CI configs (`actions/cache` on GitHub,
`cache:` on GitLab) — without that, the cache directory starts empty every run
since hosted runners are ephemeral.

Useful flags:
```bash
--no-cache              # always call the analysis engine, ignore cache
--cache-dir ./somewhere  # override cache location (default: .pipefix_cache)
--cost-estimate          # print real token usage and dollar cost for this run
```
Cache entries expire after 7 days by default (`PIPEFIX_CACHE_TTL_SECONDS` env var to change).

`--cost-estimate` uses the actual `usage` field from the Claude API response —
not an estimate — so the numbers are exact for that call. On a cache hit it
reports $0.00 for the current run, plus what the original call cost when it
was first cached, for context. Pricing constants (`INPUT_PRICE_PER_MTOK`,
`OUTPUT_PRICE_PER_MTOK` in `analyzer.py`) reflect Sonnet 4.6 rates at time of
writing — verify against [the pricing docs](https://docs.claude.com/en/docs/about-claude/pricing)
if rates may have changed.

---

## Extending the signature library

Add entries to `pipefix/detection/signatures.yaml`:

```yaml
- pattern: "your regex here"
  stage: test            # install | build | lint | test | security | docker | deploy
  language: python        # or node, go, rust, java, generic
  failure_type: test
  hint: "short human hint, also shown in offline fallback mode"
```

Nothing matched in the library still gets analyzed — it just falls through to
Claude with less pre-classification context.

---

## Project structure

```
pipefix/
├── .github/workflows/pipefix.yml
├── .gitlab-ci.yml
├── pipefix/
│   ├── main.py                  # CLI entrypoint
│   ├── analyzer.py               # Claude call + offline fallback
│   ├── extract.py                # shrinks logs to just the failure block
│   ├── cache.py                  # failure-signature cache (skip repeat API calls)
│   ├── formatter.py              # builds the markdown report
│   ├── redact.py                 # scrubs secrets before any external use
│   ├── detection/
│   │   ├── signatures.yaml       # pattern library (language x stage x type)
│   │   ├── classifier.py
│   │   └── language_detector.py
│   └── adapters/
│       ├── github_adapter.py
│       └── gitlab_adapter.py
├── sample-apps/
│   ├── python-app/                # deliberate test failure for demo
│   └── node-app/                  # deliberate test failure for demo
└── requirements.txt
```

## License

MIT
