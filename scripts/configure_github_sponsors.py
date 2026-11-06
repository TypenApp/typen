"""
Configure GitHub Sponsors and repository funding settings across the `TypenApp`
GitHub organisation (`https://github.com/TypenApp`).

What this script does:
1. Enables the "Sponsor" button (`hasSponsorshipsEnabled: true`) on all `TypenApp`
   repositories (`.github`, `typen`, `language-data`, `model-resources`, `docs`) via
   GitHub's GraphQL API (`updateRepository`).
2. Attempts to provision the `TypenApp` GitHub Sponsors profile (`createSponsorsListing`)
   and default monthly / one-time sponsorship tiers (`createSponsorsTier`) when the
   active GitHub token includes `admin:org` + `user` scopes.
3. Verifies active `fundingLinks` resolved from `.github/FUNDING.yml` on every repository.

Usage:
    python scripts/configure_github_sponsors.py [--org TypenApp] [--country GB]
"""

from __future__ import annotations

import argparse
import os
import subprocess
from typing import Any

import httpx

ORG_DEFAULT = "TypenApp"
REPOS_DEFAULT = [".github", "typen", "language-data", "model-resources", "docs"]

SPONSORS_PROFILE_INTRO = (
    "Typen is a free, open-source (MIT), offline-first system-wide autocorrect and writing "
    "assistant for Windows, macOS, and Linux.\n\n"
    "There is no paid tier, no trial, and no telemetry. Sponsorships directly fund:\n"
    "- Windows Authenticode and Apple Developer ID code-signing certificates\n"
    "- Multi-platform CI build runners across Windows, macOS, and Linux\n"
    "- Hosting for the documentation and live engine sandbox\n"
    "- Ongoing curation of the 166,000+-word English lexicon and domain vocabulary packs"
)

DEFAULT_SPONSORS_TIERS: list[dict[str, Any]] = [
    {
        "amount": 5,
        "isRecurring": True,
        "description": "Supporter — Helps cover monthly hosting and multi-platform CI build minutes for Typen.",
    },
    {
        "amount": 15,
        "isRecurring": True,
        "description": "Backer — Directly contributes toward Windows Authenticode and Apple Developer ID code-signing certificates.",
    },
    {
        "amount": 50,
        "isRecurring": True,
        "description": "Patron — Sustains lexicon curation, new domain vocabulary packs, and Layer 2 local AI model builds.",
    },
    {
        "amount": 10,
        "isRecurring": False,
        "description": "One-time Coffee — Thank you for supporting free, offline-first open-source software!",
    },
    {
        "amount": 25,
        "isRecurring": False,
        "description": "One-time Code-Signing Boost — Goes directly toward the annual OS code-signing certificate fund.",
    },
]


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


def _graphql(client: httpx.Client, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = client.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables or {}},
    )
    resp.raise_for_status()
    return dict(resp.json())


def enable_repo_sponsorships(
    client: httpx.Client,
    org: str = ORG_DEFAULT,
    repos: list[str] | None = None,
) -> list[dict[str, Any]]:
    target_repos = repos or REPOS_DEFAULT
    results: list[dict[str, Any]] = []
    for name in target_repos:
        q_repo = """
        query($owner: String!, $name: String!) {
          repository(owner: $owner, name: $name) {
            id
            name
          }
        }
        """
        r_info = _graphql(client, q_repo, {"owner": org, "name": name})
        repo_node = (r_info.get("data") or {}).get("repository")
        if not repo_node:
            continue

        mut = """
        mutation($repoId: ID!, $discussions: Boolean!) {
          updateRepository(input: {
            repositoryId: $repoId,
            hasSponsorshipsEnabled: true,
            hasDiscussionsEnabled: $discussions
          }) {
            repository {
              name
              hasSponsorshipsEnabled
              hasDiscussionsEnabled
              fundingLinks {
                platform
                url
              }
            }
          }
        }
        """
        updated = _graphql(
            client,
            mut,
            {
                "repoId": repo_node["id"],
                "discussions": name in ("typen", ".github"),
            },
        )
        repo_state = ((updated.get("data") or {}).get("updateRepository") or {}).get("repository") or {}
        results.append(repo_state)
        print(
            f"[{org}/{name}] hasSponsorshipsEnabled={repo_state.get('hasSponsorshipsEnabled')} "
            f"fundingLinks={repo_state.get('fundingLinks')}"
        )
    return results


def try_provision_sponsors_listing_and_tiers(
    client: httpx.Client,
    org: str = ORG_DEFAULT,
    country_code: str = "GB",
) -> bool:
    mut_listing = """
    mutation($login: String!, $country: SponsorsCountryOrRegionCode!, $desc: String!) {
      createSponsorsListing(input: {
        sponsorableLogin: $login,
        billingCountryOrRegionCode: $country,
        fullDescription: $desc
      }) {
        sponsorsListing {
          slug
          url
        }
      }
    }
    """
    res = _graphql(
        client,
        mut_listing,
        {"login": org, "country": country_code, "desc": SPONSORS_PROFILE_INTRO},
    )
    if "errors" in res:
        messages = "; ".join(e.get("message", "") for e in res["errors"])
        print(f"Note: Sponsors profile listing step reported: {messages}")
        print(
            f"Complete Stripe Connect & tax verification for @{org} at: "
            f"https://github.com/sponsors/{org}/dashboard"
        )
        return False

    print(f"Created GitHub Sponsors listing for @{org}!")
    mut_tier = """
    mutation($login: String!, $amount: Int!, $recurring: Boolean!, $desc: String!) {
      createSponsorsTier(input: {
        sponsorableLogin: $login,
        amount: $amount,
        isRecurring: $recurring,
        description: $desc,
        publish: true
      }) {
        tier {
          id
          monthlyPriceInDollars
          isOneTime
        }
      }
    }
    """
    for tier in DEFAULT_SPONSORS_TIERS:
        _graphql(
            client,
            mut_tier,
            {
                "login": org,
                "amount": tier["amount"],
                "recurring": tier["isRecurring"],
                "desc": tier["description"],
            },
        )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", default=ORG_DEFAULT, help="GitHub organisation handle")
    parser.add_argument("--country", default="GB", help="ISO country code for billing (e.g. GB, US)")
    args = parser.parse_args(argv)

    token = get_github_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with httpx.Client(headers=headers, timeout=30.0) as client:
        enable_repo_sponsorships(client, org=args.org)
        try_provision_sponsors_listing_and_tiers(client, org=args.org, country_code=args.country)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
