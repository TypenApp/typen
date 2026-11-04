import React from "react";
import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Dash } from "@/components/Page";
import { DOC_ARTICLES, getDocBySlug } from "@/data/docs";

export function generateStaticParams() {
  return DOC_ARTICLES.map((doc) => ({ slug: doc.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const article = getDocBySlug(slug);
  return article ? { title: article.shortTitle, description: article.summary } : {};
}

export default async function DocArticlePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const article = getDocBySlug(slug);
  if (!article) notFound();

  const i = DOC_ARTICLES.findIndex((d) => d.slug === slug);
  const prev = i > 0 ? DOC_ARTICLES[i - 1] : null;
  const next = i < DOC_ARTICLES.length - 1 ? DOC_ARTICLES[i + 1] : null;

  return (
    <article className="max-w-3xl">
      <p className="eyebrow">
        {article.category} · {article.readingTime}
      </p>
      <h1 className="display mt-4 text-3xl leading-tight sm:text-4xl">{article.title}</h1>
      <p className="mt-4 text-lg leading-relaxed text-ink-muted">{article.summary}</p>

      <nav className="card mt-8 p-5 text-sm" aria-label="On this page">
        <p className="eyebrow">On this page</p>
        <ol className="mt-3 space-y-1.5">
          {article.sections.map((sec, k) => (
            <li key={sec.id} className="flex gap-3">
              <span className="font-mono text-[11px] text-ink-faint">{String(k + 1).padStart(2, "0")}</span>
              <a href={`#${sec.id}`} className="text-ink-muted hover:text-ink">
                {sec.heading}
              </a>
            </li>
          ))}
        </ol>
      </nav>

      <div className="mt-14 space-y-14">
        {article.sections.map((sec, k) => (
          <section key={sec.id} id={sec.id} className="scroll-mt-24">
            <h2 className="display text-2xl">
              <span className="eyebrow mr-3 align-middle">{String(k + 1).padStart(2, "0")}</span>
              {sec.heading}
            </h2>
            <div className="mt-4 space-y-4 text-[15px] leading-relaxed text-ink-muted">
              {sec.paragraphs.map((p, j) => (
                <p key={j}>{p}</p>
              ))}
            </div>
            {sec.bullets && (
              <ul className="mt-5 space-y-2">
                {sec.bullets.map((b, j) => (
                  <Dash key={j}>{b}</Dash>
                ))}
              </ul>
            )}
            {sec.codeBlock && (
              <div className="card mt-5 overflow-hidden">
                <div className="flex items-center justify-between border-b border-line px-4 py-2 font-mono text-[11px] text-ink-faint">
                  <span>{sec.codeBlock.title}</span>
                  <span>{sec.codeBlock.language}</span>
                </div>
                <pre className="overflow-x-auto p-4 text-xs leading-relaxed text-ink">
                  <code>{sec.codeBlock.code}</code>
                </pre>
              </div>
            )}
          </section>
        ))}
      </div>

      <div className="rule mt-16 flex justify-between gap-4 pt-6 text-sm">
        {prev ? (
          <Link href={`/docs/${prev.slug}`} className="text-ink-muted hover:text-ink">
            ← {prev.shortTitle}
          </Link>
        ) : (
          <span />
        )}
        {next && (
          <Link href={`/docs/${next.slug}`} className="text-right text-ink-muted hover:text-ink">
            {next.shortTitle} →
          </Link>
        )}
      </div>
    </article>
  );
}
