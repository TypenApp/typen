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
 * `ink-*` are foreground colours, `paper-*` are surfaces.
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
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        ink: {
          DEFAULT: "#000000",
          1: "#0a0a0a",
          2: "#171717",
          3: "#262626",
          muted: "#595959",
          faint: "#8a8a8a",
        },
        paper: {
          DEFAULT: "#ffffff",
          1: "#fafafa",
          2: "#f4f4f4",
          3: "#ececec",
        },
        line: {
          DEFAULT: "#e4e4e4",
          strong: "#c9c9c9",
        },
        proof: {
          DEFAULT: "#e5341a",
          strong: "#c42a12",
          soft: "#fdece8",
          ink: "#ffffff",
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
