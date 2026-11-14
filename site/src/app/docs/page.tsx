"use client";

import React, { useState } from "react";
import Link from "next/link";
import { DOC_ARTICLES } from "@/data/docs";

export default function DocsIndexPage() {
  const [filter, setFilter] = useState("");
  const q = filter.trim().toLowerCase();

  const docs = DOC_ARTICLES.filter((doc) => {
    if (!q) return true;
    return (
      doc.title.toLowerCase().includes(q) ||
      doc.summary.toLowerCase().includes(q) ||
      doc.sections.some(
        (s) => s.heading.toLowerCase().includes(q) || s.paragraphs.some((p) => p.toLowerCase().includes(q)),
      )
    );
  });

  return (
    <div>
      <div className="grid gap-6 border-b border-line pb-8 xl:grid-cols-12 xl:items-end">
        <div className="xl:col-span-7">
          <p className="eyebrow">Documentation</p>
          <h1 className="display mt-3 text-4xl sm:text-5xl">Guides and reference</h1>
          <p className="prose-site mt-4 max-w-2xl text-base sm:text-lg">
            <span>
              How the background service and the Settings window work, how to customise corrections, and how
              licensing and updates are handled.
            </span>
          </p>
        </div>
        <div className="xl:col-span-5">
          <input
            type="search"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter guides…"
            aria-label="Filter guides"
            className="field w-full"
          />
        </div>
      </div>

      <ol className="mt-8 grid gap-5 md:grid-cols-2">
        {docs.map((doc, i) => (
          <li key={doc.slug} className="flex">
            <Link
              href={`/docs/${doc.slug}`}
              className="card group flex w-full flex-col justify-between p-6 transition-colors hover:border-ink-faint"
            >
              <div>
                <div className="flex items-center justify-between gap-3">
                  <span className="eyebrow">{String(i + 1).padStart(2, "0")}</span>
                  <span className="rounded border border-line px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-ink-faint">
                    {doc.category}
                  </span>
                </div>
                <span className="mt-3 block font-display text-xl text-ink transition-colors group-hover:text-proof-strong">
                  {doc.title}
                </span>
                <span className="mt-2 block text-sm leading-relaxed text-ink-muted">{doc.summary}</span>
              </div>
              <span className="mt-5 block border-t border-line pt-3 font-mono text-[11px] text-ink-faint">
                {doc.readingTime}
              </span>
            </Link>
          </li>
        ))}
        {docs.length === 0 && (
          <li className="py-8 text-sm text-ink-faint md:col-span-2">No guides match “{filter}”.</li>
        )}
      </ol>
    </div>
  );
}
