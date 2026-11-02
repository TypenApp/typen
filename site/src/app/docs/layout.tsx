"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { DOC_ARTICLES } from "@/data/docs";

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="container-narrow pb-24 pt-12">
      <div className="grid gap-12 lg:grid-cols-[200px_1fr]">
        <aside className="hidden lg:block">
          <nav className="sticky top-24 space-y-0.5 text-sm">
            <Link
              href="/docs"
              className={`block rounded-md px-2.5 py-1.5 ${
                pathname === "/docs" ? "text-zinc-100" : "text-zinc-500 hover:text-zinc-200"
              }`}
            >
              Overview
            </Link>
            {DOC_ARTICLES.map((doc) => {
              const href = `/docs/${doc.slug}`;
              const active = pathname === href;
              return (
                <Link
                  key={doc.slug}
                  href={href}
                  className={`block rounded-md px-2.5 py-1.5 ${
                    active ? "bg-zinc-900 text-zinc-100" : "text-zinc-500 hover:text-zinc-200"
                  }`}
                >
                  {doc.shortTitle}
                </Link>
              );
            })}
          </nav>
        </aside>
        <div className="min-w-0">{children}</div>
      </div>
    </div>
  );
}
