"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { DOC_ARTICLES } from "@/data/docs";
import { IS_PRERELEASE, PLATFORM_RELEASES } from "@/data/releases";
import { Wordmark } from "./Brand";
import { GitHubStars } from "./GitHubStars";
interface SearchResultItem {
  title: string;
  subtitle: string;
  href: string;
  category: string;
}

const NAV_LINKS = [
  { href: "/download", label: "Download" },
  { href: "/docs", label: "Docs" },
  { href: "/donate", label: "Donate" },
];

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [searchOpen, setSearchOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((prev) => !prev);
      } else if (e.key === "Escape") {
        setSearchOpen(false);
        setMenuOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  const allSearchItems = useMemo<SearchResultItem[]>(() => {
    const items: SearchResultItem[] = [];
    for (const p of PLATFORM_RELEASES) {
      items.push({
        title: `Download for ${p.osName}`,
        subtitle:
          p.status === "beta"
            ? p.artifacts.map((a) => a.filename).join(" · ")
            : "Not built for this release yet",
        href: "/download",
        category: "Download",
      });
    }
    items.push({
      title: "Donate",
      subtitle: "Free and open source · funded by donations only",
      href: "/donate",
      category: "Donate",
    });
    for (const doc of DOC_ARTICLES) {
      items.push({
        title: doc.title,
        subtitle: doc.summary,
        href: `/docs/${doc.slug}`,
        category: "Docs",
      });
      for (const sec of doc.sections) {
        items.push({
          title: `${doc.shortTitle} › ${sec.heading}`,
          subtitle: sec.paragraphs[0] || doc.summary,
          href: `/docs/${doc.slug}#${sec.id}`,
          category: "Docs",
        });
      }
    }
    return items;
  }, []);

  const filteredResults = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return allSearchItems.slice(0, 8);
    return allSearchItems
      .filter(
        (item) =>
          item.title.toLowerCase().includes(q) ||
          item.subtitle.toLowerCase().includes(q) ||
          item.category.toLowerCase().includes(q)
      )
      .slice(0, 10);
  }, [query, allSearchItems]);

  return (
    <>
      {/* A floating bar: detached from the top edge, pill-shaped, translucent over the page. */}
      <header className="sticky top-3 z-40 sm:top-4">
        <div className="container-site">
          <div className="relative rounded-[28px] border border-line bg-paper/80 shadow-[0_8px_30px_-12px_rgb(var(--ink)/0.25)] backdrop-blur-xl">
            <div className="flex h-14 items-center justify-between gap-2 pl-3.5 pr-2 sm:h-[60px] sm:pl-5 sm:pr-2.5">
              <Wordmark beta={IS_PRERELEASE} />

              <nav className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-1 md:flex" aria-label="Primary">
                {NAV_LINKS.map((link) => {
                  const isActive = pathname?.startsWith(link.href);
                  return (
                    <Link
                      key={link.href}
                      href={link.href}
                      className={`rounded-full px-3.5 py-2 text-sm transition-colors ${
                        isActive ? "bg-paper-2 text-ink" : "text-ink-muted hover:bg-paper-2 hover:text-ink"
                      }`}
                      aria-current={isActive ? "page" : undefined}
                    >
                      {link.label}
                    </Link>
                  );
                })}
              </nav>

              <div className="flex items-center gap-1.5 sm:gap-2">
                <button
                  type="button"
                  onClick={() => setSearchOpen(true)}
                  aria-label="Search"
                  className="icon-btn hidden lg:inline-flex"
                  title="Search (Ctrl K)"
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
                    <circle cx="11" cy="11" r="6.5" />
                    <path d="m20 20-4.3-4.3" />
                  </svg>
                </button>
                <GitHubStars />
                <Link href="/download" className="btn-primary btn-pill hidden h-10 px-4 sm:inline-flex">
                  Download
                </Link>
                <button
                  type="button"
                  className="icon-btn md:hidden"
                  aria-label={menuOpen ? "Close menu" : "Open menu"}
                  aria-expanded={menuOpen}
                  onClick={() => setMenuOpen((v) => !v)}
                >
                  <span className="relative block h-3 w-4">
                    <span
                      className={`absolute left-0 top-0 h-px w-4 bg-current transition-transform ${
                        menuOpen ? "translate-y-[6px] rotate-45" : ""
                      }`}
                    />
                    <span
                      className={`absolute left-0 top-[6px] h-px w-4 bg-current transition-opacity ${
                        menuOpen ? "opacity-0" : ""
                      }`}
                    />
                    <span
                      className={`absolute left-0 top-3 h-px w-4 bg-current transition-transform ${
                        menuOpen ? "-translate-y-[6px] -rotate-45" : ""
                      }`}
                    />
                  </span>
                </button>
              </div>
            </div>

            {menuOpen && (
              <nav
                className="absolute inset-x-0 top-full mt-2 flex flex-col gap-0.5 rounded-[24px] border border-line bg-paper p-2 shadow-[0_16px_40px_-16px_rgb(var(--ink)/0.35)] md:hidden"
                aria-label="Mobile"
              >
                {NAV_LINKS.map((link) => {
                  const isActive = pathname?.startsWith(link.href);
                  return (
                    <Link
                      key={link.href}
                      href={link.href}
                      className={`rounded-2xl px-3.5 py-2.5 text-sm ${
                        isActive ? "bg-paper-2 text-ink" : "text-ink-muted hover:bg-paper-2 hover:text-ink"
                      }`}
                      aria-current={isActive ? "page" : undefined}
                    >
                      {link.label}
                    </Link>
                  );
                })}
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    setSearchOpen(true);
                  }}
                  className="rounded-2xl px-3.5 py-2.5 text-left text-sm text-ink-muted hover:bg-paper-2 hover:text-ink"
                >
                  Search
                </button>
                <Link href="/download" className="btn-primary btn-pill mt-1 h-10 sm:hidden">
                  Download
                </Link>
              </nav>
            )}
          </div>
        </div>
      </header>

      {searchOpen && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center bg-ink/40 p-4 pt-24"
          onClick={() => setSearchOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-label="Search"
        >
          <div className="card w-full max-w-xl overflow-hidden shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center border-b border-line px-4 py-3">
              <input
                type="text"
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search docs and downloads…"
                className="w-full bg-transparent text-sm text-ink placeholder-ink-faint outline-none"
              />
              <kbd className="kbd">Esc</kbd>
            </div>
            <div className="max-h-96 overflow-y-auto p-2">
              {filteredResults.length === 0 ? (
                <p className="py-8 text-center text-sm text-ink-faint">No results for “{query}”.</p>
              ) : (
                filteredResults.map((item) => (
                  <button
                    key={item.href + item.title}
                    type="button"
                    onClick={() => {
                      setSearchOpen(false);
                      router.push(item.href);
                    }}
                    className="flex w-full flex-col items-start rounded px-3 py-2.5 text-left transition hover:bg-paper-2"
                  >
                    <div className="flex w-full items-center justify-between gap-3">
                      <span className="text-sm text-ink">{item.title}</span>
                      <span className="eyebrow shrink-0 tracking-normal">{item.category}</span>
                    </div>
                    <p className="mt-0.5 line-clamp-1 text-xs text-ink-faint">{item.subtitle}</p>
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
