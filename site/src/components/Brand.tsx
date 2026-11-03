import React from "react";
import Link from "next/link";

/** The mark: "Aa" over the proofreader's squiggle. Same drawing as app/icon.svg. */
export function BrandMark({ size = 28, className = "" }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      aria-hidden="true"
      className={className}
      focusable="false"
    >
      <rect width="64" height="64" rx="14" fill="#f3efe8" />
      <text
        x="32"
        y="38"
        textAnchor="middle"
        fontFamily="var(--font-display), Georgia, serif"
        fontSize="34"
        fill="#0e0d0c"
      >
        Aa
      </text>
      <path
        d="M12 50 q4 -5 8 0 t8 0 t8 0 t8 0 t8 0"
        fill="none"
        stroke="#ff5a3c"
        strokeWidth="3.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Wordmark: the product name with the squiggle under "Correct" — the typo that got fixed. */
export function Wordmark({ withMark = true, beta = false }: { withMark?: boolean; beta?: boolean }) {
  return (
    <Link href="/" className="group inline-flex items-center gap-2.5" aria-label="AutoCorrect home">
      {withMark && <BrandMark size={26} />}
      <span className="font-display text-[22px] leading-none tracking-[-0.01em] text-paper">
        Auto<span className="wordmark-squiggle">Correct</span>
      </span>
      {beta && (
        <span className="ml-0.5 rounded-full border border-proof/50 px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-proof">
          beta
        </span>
      )}
    </Link>
  );
}
