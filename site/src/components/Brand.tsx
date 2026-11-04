import React from "react";
import Link from "next/link";

/**
 * The mark: "Aa_" — two cases of the letter and a text cursor — on a tile,
 * with the proofreader's squiggle centred under all three. The tile is ink
 * and the glyphs are paper, so in the light theme it is a black tile with
 * white letters and in the dark theme the reverse. Geometry is measured
 * against Syne Bold at 24px: "Aa" is 37.5 wide, the cursor bar 8, a 3px gap
 * between them, the whole group centred on x=32. Same drawing as app/icon.svg.
 */
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
      <rect width="64" height="64" rx="14" className="fill-ink" />
      <text
        x="7.75"
        y="36"
        fontFamily="var(--font-sans), system-ui, sans-serif"
        fontWeight="700"
        fontSize="24"
        letterSpacing="-1"
        className="fill-paper"
      >
        Aa
      </text>
      {/* The underscore: a text cursor sitting where the next letter goes. */}
      <rect x="48.25" y="33" width="8" height="3" rx="1" className="fill-paper" />
      {/* Six humps of 8 = 48 wide, from x=8 to x=56: exactly the width of "Aa_". */}
      <path
        d="M8 46 q4 -5 8 0 t8 0 t8 0 t8 0 t8 0 t8 0"
        fill="none"
        strokeWidth="3.2"
        strokeLinecap="round"
        className="stroke-proof"
      />
    </svg>
  );
}

/** Wordmark: the mark and the product name, set in Syne ExtraBold. */
export function Wordmark({ withMark = true, beta = false }: { withMark?: boolean; beta?: boolean }) {
  return (
    <Link href="/" className="group inline-flex items-center gap-2.5" aria-label="Tact home">
      {withMark && <BrandMark size={26} />}
      <span className="font-display text-[22px] font-extrabold leading-none tracking-[-0.03em] text-ink">Tact</span>
      {beta && (
        <span className="ml-0.5 rounded-full border border-proof/50 px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-proof">
          beta
        </span>
      )}
    </Link>
  );
}
