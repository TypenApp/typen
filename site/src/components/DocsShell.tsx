"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { DOC_ARTICLES } from "@/data/docs";

export function DocsShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const categories = Array.from(new Set(DOC_ARTICLES.map((d) => d.category)));

  return (
    <div className="container-site pb-8 pt-12 sm:pt-16">
      <div className="grid gap-12 lg:grid-cols-[220px_1fr]">
        <aside className="hidden lg:block">
          <nav className="sticky top-24 text-sm" aria-label="Documentation">
            <Link
              href="/docs"
              className={`block py-1.5 ${pathname === "/docs" ? "text-ink" : "text-ink-muted hover:text-ink"}`}
            >
              Overview
            </Link>
            {categories.map((cat) => (
              <div key={cat} className="mt-5">
                <p className="eyebrow">{cat}</p>
                <ul className="mt-2 border-l border-line">
                  {DOC_ARTICLES.filter((d) => d.category === cat).map((doc) => {
                    const href = `/docs/${doc.slug}`;
                    const active = pathname === href;
                    return (
                      <li key={doc.slug}>
                        <Link
                          href={href}
                          className={`-ml-px block border-l py-1.5 pl-4 transition-colors ${
                            active
                              ? "border-proof text-ink"
                              : "border-transparent text-ink-muted hover:border-line-strong hover:text-ink"
                          }`}
                          aria-current={active ? "page" : undefined}
                        >
                          {doc.shortTitle}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>
        </aside>
        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}
