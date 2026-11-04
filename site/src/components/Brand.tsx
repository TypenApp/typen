import React from "react";
import Link from "next/link";

/**
 * The mark: "Aa_" — two cases of the letter and a text cursor — over the
 * proofreader's squiggle. Black on white by default; `inverted` swaps the two.
 * Same drawing as app/icon.svg.
 */
export function BrandMark({
  size = 28,
  className = "",
  inverted = false,
}: {
  size?: number;
  className?: string;
  inverted?: boolean;
}) {
  const paper = inverted ? "#000000" : "#ffffff";
  const ink = inverted ? "#ffffff" : "#000000";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      aria-hidden="true"
      className={className}
      focusable="false"
    >
      <rect width="64" height="64" rx="14" fill={paper} />
      <rect x="1" y="1" width="62" height="62" rx="13" fill="none" stroke={ink} strokeWidth="2" />
      <text
        x="27"
        y="39"
        textAnchor="middle"
        fontFamily="var(--font-sans), system-ui, sans-serif"
        fontWeight="700"
        fontSize="24"
        letterSpacing="-1"
        fill={ink}
      >
        Aa
      </text>
      {/* The underscore: a text cursor sitting where the next letter goes. */}
      <rect x="44" y="36" width="9" height="3" rx="1" fill={ink} />
      <path
        d="M12 50 q4 -5 8 0 t8 0 t8 0 t8 0 t8 0"
        fill="none"
        stroke="#e5341a"
        strokeWidth="3.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Wordmark: the product name with the squiggle under it — the typo that got fixed. */
export function Wordmark({ withMark = true, beta = false }: { withMark?: boolean; beta?: boolean }) {
  return (
    <Link href="/" className="group inline-flex items-center gap-2.5" aria-label="Tact home">
      {withMark && <BrandMark size={26} />}
      <span className="font-display text-[22px] font-bold leading-none tracking-[-0.03em] text-ink">
        <span className="wordmark-squiggle">Tact</span>
      </span>
      {beta && (
        <span className="ml-0.5 rounded-full border border-proof/50 px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-proof">
          beta
        </span>
      )}
    </Link>
  );
}
