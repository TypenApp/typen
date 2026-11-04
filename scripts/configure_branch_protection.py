"""
Apply branch protection rulesets to every `TypenApp` repository via the GitHub
REST API (`/repos/{owner}/{repo}/rulesets`).

Policy applied to the default branch (and `master` on `typen`):

| Setting                         | Configuration                                   |
| ------------------------------- | ----------------------------------------------- |
| Require pull request            | ON                                              |
| Required approvals              | 1                                               |
| Dismiss stale approvals         | ON                                              |
| Require conversation resolution | ON                                              |
| Require status checks           | ON for repositories that have a CI workflow     |
| Block force pushes              | ON                                              |
| Restrict deletions              | ON                                              |
| Require signed commits          | Optional (off by default; `--require-signatures`)|
| Bypass list                     | Organisation owners + repository Admin role     |

Usage:
    python scripts/configure_branch_protection.py [--org TypenApp] [--require-signatures] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from typing import Any

import httpx

ORG_DEFAULT = "TypenApp"
RULESET_NAME = "Protected default branch"

# GitHub's built-in repository role IDs for ruleset `RepositoryRole` bypass actors
# (1 = Read, 2 = Triage, 3 = Write, 4 = Maintain, 5 = Admin).
REPOSITORY_ADMIN_ROLE_ID = 5

# Required status-check contexts are the GitHub Actions *job names* from each
# repository's `.github/workflows/ci.yml`. `.github` has no CI, so it gets no
# status-check rule until one exists.
REPO_STATUS_CHECKS: dict[str, list[str]] = {
    ".github": [],
    "typen": [
        "Lint (ruff) & type-check",
        "Tests (windows-latest, py3.12)",
        "Tests (macos-latest, py3.12)",
        "Tests (ubuntu-latest, py3.12)",
        "Tests (ubuntu-latest, py3.11)",
        "Tests (ubuntu-latest, py3.13)",
        "Site (Next.js build + live-demo function)",
    ],
    "language-data": ["Lexicon compile & held-out quality gate"],
    "model-resources": ["Validate model catalog & Ed25519 signing"],
    "docs": ["Verify Markdown guides & relative links"],
}

# Branches protected per repository, in addition to the default branch.
EXTRA_BRANCHES: dict[str, list[str]] = {
    "typen": ["refs/heads/master"],
}


def get_github_token() -> str:
    env_tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if env_tok:
        return env_tok.strip()
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input=b"protocol=https\nhost=github.com\n\n",
        capture_output=True,
        check=True,
    )
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("Could not obtain GitHub token from GITHUB_TOKEN or git credential fill")


def build_ruleset(repo_name: str, *, require_signatures: bool = False) -> dict[str, Any]:
    rules: list[dict[str, Any]] = [
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews_on_push": True,
                "require_code_owner_review": False,
                "require_last_push_approval": False,
                "required_review_thread_resolution": True,
                "allowed_merge_methods": ["merge", "squash", "rebase"],
            },
        },
    ]
    checks = REPO_STATUS_CHECKS.get(repo_name, [])
    if checks:
        rules.append(
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": [{"context": c} for c in checks],
                },
            }
        )
    if require_signatures:
        rules.append({"type": "required_signatures"})

    include = ["~DEFAULT_BRANCH", *EXTRA_BRANCHES.get(repo_name, [])]
    return {
        "name": RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        # Minimal bypass list, deliberately redundant so the maintainer keeps the
        # ability to merge indefinitely:
        #   * Organisation owners (the maintainer is an owner of TypenApp).
        #   * Repository "Admin" role (actor_id 5) - independent of org role, so a
        #     future change to org membership cannot silently lock the maintainer
        #     out of merging. With a single maintainer, "1 required approval"
        #     can never be satisfied without this bypass (no self-approval).
        # `bypass_mode: "always"` covers both pull-request merges and pushes.
        "bypass_actors": [
            {"actor_id": 1, "actor_type": "OrganizationAdmin", "bypass_mode": "always"},
            {"actor_id": REPOSITORY_ADMIN_ROLE_ID, "actor_type": "RepositoryRole", "bypass_mode": "always"},
        ],
        "conditions": {"ref_name": {"include": include, "exclude": []}},
        "rules": rules,
    }


def apply_ruleset(client: httpx.Client, org: str, repo_name: str, ruleset: dict[str, Any]) -> dict[str, Any]:
    base = f"https://api.github.com/repos/{org}/{repo_name}/rulesets"
    existing = client.get(base)
    existing.raise_for_status()
    match = next((r for r in existing.json() if r.get("name") == RULESET_NAME), None)
    if match:
        resp = client.put(f"{base}/{match['id']}", json=ruleset)
    else:
        resp = client.post(base, json=ruleset)
    if not resp.is_success:
        raise RuntimeError(f"{org}/{repo_name}: {resp.status_code} {resp.text}")
    return dict(resp.json())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org", default=ORG_DEFAULT)
    parser.add_argument("--require-signatures", action="store_true", help="Also require signed commits")
    parser.add_argument("--dry-run", action="store_true", help="Print rulesets without applying them")
    args = parser.parse_args(argv)

    if args.dry_run:
        for name in REPO_STATUS_CHECKS:
            print(f"--- {args.org}/{name}")
            print(json.dumps(build_ruleset(name, require_signatures=args.require_signatures), indent=2))
        return 0

    headers = {
        "Authorization": f"Bearer {get_github_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(headers=headers, timeout=30.0) as client:
        for name in REPO_STATUS_CHECKS:
            ruleset = build_ruleset(name, require_signatures=args.require_signatures)
            applied = apply_ruleset(client, args.org, name, ruleset)
            rule_types = [r["type"] for r in applied.get("rules", [])]
            print(
                f"[{args.org}/{name}] ruleset #{applied['id']} {applied['enforcement']} "
                f"on {applied['conditions']['ref_name']['include']}: {', '.join(rule_types)}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
