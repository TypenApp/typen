"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { DOC_ARTICLES } from "@/data/docs";
import { IS_PRERELEASE, PLATFORM_RELEASES } from "@/data/releases";
import { Wordmark } from "./Brand";
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
      <header className="sticky top-0 z-40 border-b border-line bg-paper/85 backdrop-blur-md">
        <div className="container-site flex h-16 items-center justify-between">
          <div className="flex items-center gap-10">
            <Wordmark beta={IS_PRERELEASE} />
            <nav className="hidden items-center gap-7 md:flex" aria-label="Primary">
              {NAV_LINKS.map((link) => {
                const isActive = pathname?.startsWith(link.href);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={`text-sm transition-colors ${
                      isActive ? "text-ink" : "text-ink-muted hover:text-ink"
                    }`}
                    aria-current={isActive ? "page" : undefined}
                  >
                    {link.label}
                  </Link>
                );
              })}
            </nav>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSearchOpen(true)}
              aria-label="Search"
              className="btn-secondary hidden h-9 gap-3 px-3 text-xs text-ink-muted sm:inline-flex"
            >
              <span>Search</span>
              <kbd className="kbd">Ctrl K</kbd>
            </button>
            <Link href="/download" className="btn-primary hidden h-9 sm:inline-flex">
              Download
            </Link>
            <button
              type="button"
              className="btn-ghost h-9 md:hidden"
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((v) => !v)}
            >
              <span className="relative block h-3 w-5">
                <span
                  className={`absolute left-0 top-0 h-px w-5 bg-current transition-transform ${
                    menuOpen ? "translate-y-[6px] rotate-45" : ""
                  }`}
                />
                <span
                  className={`absolute left-0 top-[6px] h-px w-5 bg-current transition-opacity ${
                    menuOpen ? "opacity-0" : ""
                  }`}
                />
                <span
                  className={`absolute left-0 top-3 h-px w-5 bg-current transition-transform ${
                    menuOpen ? "-translate-y-[6px] -rotate-45" : ""
                  }`}
                />
              </span>
            </button>
          </div>
        </div>
        {menuOpen && (
          <nav className="container-site rule flex flex-col gap-1 py-3 md:hidden" aria-label="Mobile">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="rounded px-2 py-2 text-sm text-ink-muted hover:bg-paper-2 hover:text-ink"
              >
                {link.label}
              </Link>
            ))}
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                setSearchOpen(true);
              }}
              className="rounded px-2 py-2 text-left text-sm text-ink-muted hover:bg-paper-2 hover:text-ink"
            >
              Search
            </button>
          </nav>
        )}
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
