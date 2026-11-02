"use client";

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { DOC_ARTICLES } from "@/data/docs";
import { IS_PRERELEASE, WINDOWS_INSTALLER } from "@/data/releases";

interface SearchResultItem {
  title: string;
  subtitle: string;
  href: string;
  category: string;
}

const NAV_LINKS = [
  { href: "/download", label: "Download" },
  { href: "/docs", label: "Docs" },
  { href: "/pricing", label: "Pricing" },
];

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen((prev) => !prev);
      } else if (e.key === "Escape") {
        setSearchOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const allSearchItems = useMemo<SearchResultItem[]>(() => {
    const items: SearchResultItem[] = [
      {
        title: "Download for Windows",
        subtitle: WINDOWS_INSTALLER
          ? `${WINDOWS_INSTALLER.filename} · ${WINDOWS_INSTALLER.sizeFormatted}`
          : "Installer and portable build",
        href: "/download",
        category: "Download",
      },
      {
        title: "Pricing",
        subtitle: "Standard and Pro perpetual licences · USD, NGN, GHS, KES",
        href: "/pricing",
        category: "Pricing",
      },
    ];
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
      <header className="sticky top-0 z-40 border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur">
        <div className="container-narrow flex h-14 items-center justify-between">
          <div className="flex items-center gap-8">
            <Link href="/" className="flex items-center gap-2.5">
              <span className="flex h-7 w-7 items-center justify-center rounded-md bg-blue-600 text-sm font-semibold text-white">
                ✓
              </span>
              <span className="text-sm font-semibold text-zinc-100">AutoCorrect</span>
              {IS_PRERELEASE && (
                <span className="rounded border border-zinc-700 px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide text-zinc-400">
                  Beta
                </span>
              )}
            </Link>
            <nav className="hidden items-center gap-1 md:flex">
              {NAV_LINKS.map((link) => {
                const isActive = pathname?.startsWith(link.href);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={`rounded-md px-3 py-1.5 text-sm transition ${
                      isActive ? "text-zinc-100" : "text-zinc-400 hover:text-zinc-100"
                    }`}
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
              className="hidden items-center gap-2 rounded-md border border-zinc-800 px-2.5 py-1.5 text-xs text-zinc-400 transition hover:border-zinc-700 hover:text-zinc-200 sm:flex"
            >
              <span>Search</span>
              <kbd className="rounded border border-zinc-700 px-1 text-[10px] text-zinc-400">Ctrl K</kbd>
            </button>
            <Link
              href="/download"
              className="rounded-md bg-zinc-100 px-3.5 py-1.5 text-sm font-medium text-zinc-900 transition hover:bg-white"
            >
              Download
            </Link>
          </div>
        </div>
      </header>

      {searchOpen && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 p-4 pt-24"
          onClick={() => setSearchOpen(false)}
        >
          <div
            className="w-full max-w-xl overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center border-b border-zinc-800 px-4 py-3">
              <input
                type="text"
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search docs and downloads…"
                className="w-full bg-transparent text-sm text-zinc-100 placeholder-zinc-500 outline-none"
              />
              <kbd className="rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-500">
                Esc
              </kbd>
            </div>
            <div className="max-h-96 overflow-y-auto p-2">
              {filteredResults.length === 0 ? (
                <p className="py-8 text-center text-sm text-zinc-500">No results for “{query}”.</p>
              ) : (
                filteredResults.map((item) => (
                  <button
                    key={item.href + item.title}
                    type="button"
                    onClick={() => {
                      setSearchOpen(false);
                      router.push(item.href);
                    }}
                    className="flex w-full flex-col items-start rounded-lg px-3 py-2.5 text-left transition hover:bg-zinc-900"
                  >
                    <div className="flex w-full items-center justify-between gap-3">
                      <span className="text-sm text-zinc-100">{item.title}</span>
                      <span className="shrink-0 text-xs text-zinc-500">{item.category}</span>
                    </div>
                    <p className="mt-0.5 line-clamp-1 text-xs text-zinc-500">{item.subtitle}</p>
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
