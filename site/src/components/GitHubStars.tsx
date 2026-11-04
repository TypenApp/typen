"use client";

import React, { useEffect, useState } from "react";
import { GITHUB_REPO, GITHUB_REPO_URL } from "@/data/releases";
import { GitHubIcon, StarIcon } from "./Icons";

const CACHE_KEY = "tact-gh-stars";
const CACHE_TTL_MS = 60 * 60 * 1000;

function format(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1).replace(/\.0$/, "")}K`;
  return String(n);
}

/**
 * The repository's star count, read from GitHub's public API on the client
 * and cached for an hour. Renders as a pill that links to the repository;
 * until (or unless) the count arrives it is simply the GitHub mark.
 */
export function GitHubStars({ className = "" }: { className?: string }) {
  const [stars, setStars] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    try {
      const cached = sessionStorage.getItem(CACHE_KEY);
      if (cached) {
        const { n, at } = JSON.parse(cached) as { n: number; at: number };
        if (Date.now() - at < CACHE_TTL_MS) {
          setStars(n);
          return;
        }
      }
    } catch {
      /* storage unavailable */
    }
    fetch(`https://api.github.com/repos/${GITHUB_REPO}`, { headers: { Accept: "application/vnd.github+json" } })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { stargazers_count?: number } | null) => {
        if (cancelled || !data || typeof data.stargazers_count !== "number") return;
        setStars(data.stargazers_count);
        try {
          sessionStorage.setItem(CACHE_KEY, JSON.stringify({ n: data.stargazers_count, at: Date.now() }));
        } catch {
          /* storage unavailable */
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <a
      href={GITHUB_REPO_URL}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={stars === null ? "Tact on GitHub" : `Tact on GitHub, ${stars.toLocaleString()} stars`}
      title="Star Tact on GitHub"
      className={`btn-secondary btn-pill h-10 gap-2 border-line px-3.5 text-xs text-ink-muted hover:border-ink-faint hover:text-ink ${className}`}
    >
      <GitHubIcon size={16} />
      {stars !== null && stars > 0 && (
        <span className="hidden items-center gap-1 font-mono tabular-nums min-[400px]:inline-flex">
          <StarIcon size={11} className="text-ink-faint" />
          {format(stars)}
        </span>
      )}
    </a>
  );
}
