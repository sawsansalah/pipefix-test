"""
Redacts likely secrets from log text before it leaves the CI environment
and is sent to the Claude API. This matters because:
  - Pipeline logs can contain leaked tokens, keys, or env var dumps
  - Claude is a third-party processor; logs shouldn't carry live credentials
    to it, even though Anthropic doesn't train on API inputs by policy
  - Defense in depth: if a credential leaked into a log by mistake, this is
    the last line of defense before it gets sent off-box at all

This is a best-effort regex scrubber, not a guarantee. Pair it with not
logging secrets in the first place (e.g. avoid `set -x` on steps that
touch credentials).
"""

import re

# (pattern, replacement-label) pairs, checked in order
REDACTION_PATTERNS = [
    # Cloud provider keys
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_ACCESS_KEY_ID]"),
    (re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*\S+"), "aws_secret_access_key=[REDACTED]"),

    # GitHub tokens
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{30,}"), "[REDACTED_GITHUB_TOKEN]"),

    # GitLab tokens
    (re.compile(r"glpat-[A-Za-z0-9\-_]{20,}"), "[REDACTED_GITLAB_TOKEN]"),

    # Anthropic / OpenAI style keys
    (re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"), "[REDACTED_ANTHROPIC_KEY]"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED_API_KEY]"),

    # Slack tokens
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED_SLACK_TOKEN]"),

    # Generic bearer / authorization headers
    (re.compile(r"(?i)authorization:\s*bearer\s+\S+"), "Authorization: Bearer [REDACTED]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.]{20,}"), "Bearer [REDACTED]"),

    # JWTs (three dot-separated base64url segments)
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "[REDACTED_JWT]"),

    # Private key blocks
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
     "[REDACTED_PRIVATE_KEY_BLOCK]"),

    # Generic "key/secret/token/password = value" assignments in env dumps
    (re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd)\s*[=:]\s*['\"]?[^\s'\"]{6,}['\"]?"),
     lambda m: f"{m.group(1)}=[REDACTED]"),
]


def redact(text: str) -> str:
    """Return a copy of text with likely secrets replaced by redaction labels."""
    for pattern, replacement in REDACTION_PATTERNS:
        if callable(replacement):
            text = pattern.sub(replacement, text)
        else:
            text = pattern.sub(replacement, text)
    return text
