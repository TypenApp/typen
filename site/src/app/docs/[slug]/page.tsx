import React from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { DOC_ARTICLES, getDocBySlug } from "@/data/docs";

export function generateStaticParams() {
  return DOC_ARTICLES.map((doc) => ({ slug: doc.slug }));
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
      <h1 className="mt-3 text-3xl font-semibold tracking-tight text-zinc-50">{article.title}</h1>
      <p className="mt-3 text-zinc-400">{article.summary}</p>

      <nav className="mt-6 text-sm">
        <ul className="space-y-1">
          {article.sections.map((sec) => (
            <li key={sec.id}>
              <a href={`#${sec.id}`} className="text-zinc-500 hover:text-zinc-200">
                {sec.heading}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="mt-12 space-y-12">
        {article.sections.map((sec) => (
          <section key={sec.id} id={sec.id} className="scroll-mt-24">
            <h2 className="text-xl font-medium text-zinc-100">{sec.heading}</h2>
            <div className="mt-3 space-y-3 text-[15px] leading-relaxed text-zinc-300">
              {sec.paragraphs.map((p, k) => (
                <p key={k}>{p}</p>
              ))}
            </div>
            {sec.bullets && (
              <ul className="mt-4 space-y-1.5 text-sm text-zinc-300">
                {sec.bullets.map((b, k) => (
                  <li key={k} className="flex gap-2">
                    <span className="text-zinc-600">—</span>
                    <span>{b}</span>
                  </li>
                ))}
              </ul>
            )}
            {sec.codeBlock && (
              <div className="card mt-4 overflow-hidden">
                <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-2 text-xs text-zinc-500">
                  <span className="font-mono">{sec.codeBlock.title}</span>
                  <span>{sec.codeBlock.language}</span>
                </div>
                <pre className="overflow-x-auto p-4 text-xs leading-relaxed text-zinc-200">
                  <code>{sec.codeBlock.code}</code>
                </pre>
              </div>
            )}
          </section>
        ))}
      </div>

      <div className="mt-16 flex justify-between gap-4 border-t border-zinc-800 pt-6 text-sm">
        {prev ? (
          <Link href={`/docs/${prev.slug}`} className="text-zinc-400 hover:text-zinc-100">
            ← {prev.shortTitle}
          </Link>
        ) : (
          <span />
        )}
        {next && (
          <Link href={`/docs/${next.slug}`} className="text-right text-zinc-400 hover:text-zinc-100">
            {next.shortTitle} →
          </Link>
        )}
      </div>
    </article>
  );
}
