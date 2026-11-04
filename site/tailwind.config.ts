import type { Config } from "tailwindcss";

/**
 * Tact design tokens.
 *
 * Identity: text on paper. Literal black (#000) ink on literal white (#fff)
 * paper; greys exist only for secondary text and hairlines. The one accent is
 * the proofreader's red squiggle — the symbol every spell-checker shares — used
 * for the motif, status, links and focus. Syne (variable) for all headline and
 * interface text; JetBrains Mono for anything technical and for the live demo's
 * text input.
 *
 * `ink-*` are foreground colours, `paper-*` are surfaces. Every value is an RGB
 * channel triple read from a CSS variable (see globals.css), so the dark theme
 * is one class on <html> that swaps ink and paper; no component knows about it.
 */
const v = (name: string) => `rgb(var(${name}) / <alpha-value>)`;

const config: Config = {
  content: [
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/data/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        ink: {
          DEFAULT: v("--ink"),
          1: v("--ink-1"),
          2: v("--ink-2"),
          3: v("--ink-3"),
          muted: v("--ink-muted"),
          faint: v("--ink-faint"),
        },
        paper: {
          DEFAULT: v("--paper"),
          1: v("--paper-1"),
          2: v("--paper-2"),
          3: v("--paper-3"),
        },
        line: {
          DEFAULT: v("--line"),
          strong: v("--line-strong"),
        },
        proof: {
          DEFAULT: v("--proof"),
          strong: v("--proof-strong"),
          soft: v("--proof-soft"),
        },
      },
      borderRadius: {
        DEFAULT: "10px",
        lg: "14px",
      },
      maxWidth: {
        site: "66rem",
      },
      keyframes: {
        caret: {
          "0%, 49%": { opacity: "1" },
          "50%, 100%": { opacity: "0" },
        },
      },
      animation: {
        caret: "caret 1.1s steps(1) infinite",
      },
    },
  },
  plugins: [],
};

export default config;
