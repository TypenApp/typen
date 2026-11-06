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
      <p className="eyebrow">Documentation</p>
      <h1 className="display mt-4 text-4xl sm:text-5xl">Guides and reference</h1>
      <p className="prose-site mt-5 max-w-2xl text-lg">
        <span>
          How the background service and the Settings window work, how to customise corrections, and how
          licensing and updates are handled.
        </span>
      </p>
      <input
        type="search"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter guides…"
        aria-label="Filter guides"
        className="field mt-8 max-w-md"
      />

      <ol className="mt-10 divide-y divide-line border-y border-line">
        {docs.map((doc, i) => (
          <li key={doc.slug}>
            <Link href={`/docs/${doc.slug}`} className="group grid gap-2 py-6 sm:grid-cols-[56px_160px_1fr] sm:gap-6">
              <span className="eyebrow pt-1.5">{String(i + 1).padStart(2, "0")}</span>
              <span className="pt-1 text-xs text-ink-faint">{doc.category}</span>
              <span className="min-w-0">
                <span className="block font-display text-xl text-ink transition-colors group-hover:text-proof-strong">
                  {doc.title}
                </span>
                <span className="mt-1.5 block text-sm leading-relaxed text-ink-muted">{doc.summary}</span>
                <span className="mt-2 block font-mono text-[11px] text-ink-faint">{doc.readingTime}</span>
              </span>
            </Link>
          </li>
        ))}
        {docs.length === 0 && <li className="py-8 text-sm text-ink-faint">No guides match “{filter}”.</li>}
      </ol>
    </div>
  );
}
