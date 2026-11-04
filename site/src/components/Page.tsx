import React from "react";

/**
 * Shared page grammar. Every page opens with a PageHeader and is built from
 * numbered Sections, so Download, Donate and Docs read as one site.
 */

export function PageHeader({
  eyebrow,
  title,
  lede,
  children,
}: {
  eyebrow: string;
  title: React.ReactNode;
  lede?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <header className="container-site pb-10 pt-14 sm:pt-20">
      <p className="eyebrow">{eyebrow}</p>
      <h1 className="display mt-4 max-w-3xl text-4xl leading-[1.05] sm:text-5xl">{title}</h1>
      {lede && <div className="prose-site mt-5 max-w-2xl text-lg">{lede}</div>}
      {children}
    </header>
  );
}

export function Section({
  index,
  title,
  aside,
  id,
  children,
  className = "",
}: {
  index?: string;
  title: React.ReactNode;
  aside?: React.ReactNode;
  id?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={`container-site scroll-mt-24 py-12 sm:py-16 ${className}`}>
      <div className="rule flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2 pt-5">
        <h2 className="display text-2xl sm:text-3xl">
          {index && <span className="eyebrow mr-4 align-middle">{index}</span>}
          {title}
        </h2>
        {aside && <div className="text-sm text-ink-muted">{aside}</div>}
      </div>
      <div className="mt-8">{children}</div>
    </section>
  );
}

/** Before → after, the way the engine sees it. The one visual motif of the brand. */
export function Correction({ from, to, className = "" }: { from: string; to: string; className?: string }) {
  return (
    <span className={`inline-flex flex-wrap items-baseline gap-x-2 ${className}`}>
      <span className="typo">{from}</span>
      <span aria-hidden="true" className="text-ink-faint">
        →
      </span>
      <span className="text-ink">{to}</span>
    </span>
  );
}

export function Check({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex gap-3 text-sm leading-relaxed text-ink-muted">
      <span aria-hidden="true" className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-proof" />
      <span>{children}</span>
    </li>
  );
}

export function Dash({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex gap-3 text-sm leading-relaxed text-ink-muted">
      <span aria-hidden="true" className="mt-[10px] h-px w-3 shrink-0 bg-line-strong" />
      <span>{children}</span>
    </li>
  );
}
