import type { Config } from "tailwindcss";

/**
 * AutoCorrect design tokens.
 *
 * Identity: "the squiggle, resolved" — the one symbol every spell-checker shares
 * is the wavy red line under a typo. The site is set in ink (warm near-black)
 * with paper-white text; the proofreader's red is reserved for the squiggle
 * motif, status, links and focus. Serif display for headlines (an editorial,
 * writing-tool voice), Inter for interface text, JetBrains Mono for anything
 * technical (hashes, keys, commands).
 */
const config: Config = {
  content: [
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/data/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)", "Inter", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Georgia", "serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        ink: {
          DEFAULT: "#0e0d0c",
          1: "#151311",
          2: "#1c1916",
          3: "#242019",
        },
        line: {
          DEFAULT: "#2b2622",
          strong: "#3b352f",
        },
        paper: {
          DEFAULT: "#f3efe8",
          muted: "#a79f94",
          faint: "#6f6860",
        },
        proof: {
          DEFAULT: "#ff5a3c",
          strong: "#ff7b61",
          soft: "#3a1a14",
          ink: "#1a0b07",
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
