"use client";

import React, { useEffect, useState } from "react";

export const THEME_STORAGE_KEY = "tact-theme";

/**
 * Runs inline in <head> before paint so the first frame already has the right
 * theme. Stored choice wins; otherwise follow the OS.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var s=localStorage.getItem("${THEME_STORAGE_KEY}");var d=s?s==="dark":matchMedia("(prefers-color-scheme: dark)").matches;if(d)document.documentElement.classList.add("dark");}catch(e){}})();`;

function readTheme(): "light" | "dark" {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function ThemeToggle({ className = "" }: { className?: string }) {
  // Rendered as "light" on the server; corrected after mount from the <html> class.
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    setTheme(readTheme());
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (localStorage.getItem(THEME_STORAGE_KEY)) return; // explicit choice wins
      document.documentElement.classList.toggle("dark", mq.matches);
      setTheme(readTheme());
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    localStorage.setItem(THEME_STORAGE_KEY, next);
    setTheme(next);
  };

  const label = theme === "dark" ? "Switch to light theme" : "Switch to dark theme";
  return (
    <button type="button" onClick={toggle} aria-label={label} title={label} className={`btn-ghost h-9 w-9 px-0 ${className}`}>
      {/* Half-filled disc: the page, half ink, half paper. Rotates on toggle. */}
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        aria-hidden="true"
        className={`transition-transform duration-300 ${theme === "dark" ? "rotate-180" : ""}`}
      >
        <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M8 1.5 a6.5 6.5 0 0 1 0 13 Z" fill="currentColor" />
      </svg>
    </button>
  );
}
