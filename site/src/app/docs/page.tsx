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
        (s) => s.heading.toLowerCase().includes(q) || s.paragraphs.some((p) => p.toLowerCase().includes(q))
      )
    );
  });

  return (
    <div>
      <p className="eyebrow">Documentation</p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight text-zinc-50">Guides and reference</h1>
      <p className="mt-3 max-w-2xl text-zinc-400">
        How the background service and the Settings window work, how to
        customise corrections, and how licensing and updates are handled.
      </p>
      <input
        type="text"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder="Filter guides…"
        className="mt-6 w-full max-w-md rounded-lg border border-zinc-800 bg-zinc-950 px-3.5 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:border-zinc-600 focus:outline-none"
      />

      <ul className="mt-8 divide-y divide-zinc-800 border-y border-zinc-800">
        {docs.map((doc) => (
          <li key={doc.slug}>
            <Link href={`/docs/${doc.slug}`} className="group flex flex-col gap-1 py-5 sm:flex-row sm:items-baseline sm:gap-6">
              <span className="w-40 shrink-0 text-xs text-zinc-500">{doc.category}</span>
              <span className="min-w-0">
                <span className="block font-medium text-zinc-100 group-hover:text-blue-400">{doc.title}</span>
                <span className="mt-1 block text-sm text-zinc-400">{doc.summary}</span>
              </span>
            </Link>
          </li>
        ))}
        {docs.length === 0 && <li className="py-8 text-sm text-zinc-500">No guides match “{filter}”.</li>}
      </ul>
    </div>
  );
}
