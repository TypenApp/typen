import React from "react";
import Link from "next/link";

/**
 * The mark: "Aa_" — two cases of the letter and a text cursor — on a wide
 * tile, with the proofreader's squiggle centred under all three. The tile is
 * ink and the glyphs are paper, so in the light theme it is a black tile with
 * white letters and in the dark theme the reverse.
 *
 * Geometry (viewBox 88×64), measured against Syne Bold at 24px: "Aa" spans
 * x≈20..53.4 and the underscore sits flush next to "a" at x=54.25..68 (width
 * 13.75), so the "Aa_" group is 48 wide and sits at x=20..68. The glyphs span
 * y≈19 (cap height) to y≈47.6 (bottom of the squiggle), leaving ~17–19px above
 * and below and 20px either side: the mark breathes at least as much
 * horizontally as vertically and is never a square. Same drawing as
 * app/icon.svg.
 */
export const MARK_WIDTH = 88;
export const MARK_HEIGHT = 64;

export function BrandMark({ size = 28, className = "" }: { size?: number; className?: string }) {
  const width = Math.round((size * MARK_WIDTH) / MARK_HEIGHT);
  return (
    <svg
      width={width}
      height={size}
      viewBox={`0 0 ${MARK_WIDTH} ${MARK_HEIGHT}`}
      aria-hidden="true"
      className={className}
      focusable="false"
    >
      <rect width={MARK_WIDTH} height={MARK_HEIGHT} rx="14" className="fill-ink" />
      <text
        x="19.75"
        y="36"
        fontFamily="var(--font-sans), system-ui, sans-serif"
        fontWeight="700"
        fontSize="24"
        letterSpacing="-1"
        className="fill-paper"
      >
        Aa
      </text>
      {/* The underscore: full-width and flush against the lowercase "a". */}
      <rect x="54.25" y="33" width="13.75" height="3" rx="1" className="fill-paper" />
      {/* Six humps of 8 = 48 wide, from x=20 to x=68: exactly the width of "Aa_". */}
      <path
        d="M20 46 q4 -5 8 0 t8 0 t8 0 t8 0 t8 0 t8 0"
        fill="none"
        strokeWidth="3.2"
        strokeLinecap="round"
        className="stroke-proof"
      />
    </svg>
  );
}

/**
 * Wordmark: the mark and the product name, set in Syne ExtraBold. Maturity is a
 * per-platform property (the Windows build is stable, macOS and Linux are in
 * beta), so the wordmark itself carries no channel badge.
 */
export function Wordmark({ withMark = true }: { withMark?: boolean }) {
  return (
    <Link href="/" className="group inline-flex items-center gap-2.5" aria-label="Typen home">
      {withMark && <BrandMark size={26} />}
      <span className="font-display text-[22px] font-extrabold leading-none tracking-[-0.03em] text-ink">Typen</span>
    </Link>
  );
}
