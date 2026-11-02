import React from "react";
import Link from "next/link";
import { FULL_VERSION, RESOURCE_BUNDLE_VERSION } from "@/data/releases";

export function Footer() {
  return (
    <footer className="border-t border-zinc-800/80">
      <div className="container-narrow flex flex-col gap-4 py-8 text-sm text-zinc-500 sm:flex-row sm:items-center sm:justify-between">
        <p>
          AutoCorrect Desktop {FULL_VERSION} · lexicon {RESOURCE_BUNDLE_VERSION}
        </p>
        <nav className="flex flex-wrap gap-x-6 gap-y-2">
          <Link href="/download" className="hover:text-zinc-200">
            Download
          </Link>
          <Link href="/docs" className="hover:text-zinc-200">
            Docs
          </Link>
          <Link href="/pricing" className="hover:text-zinc-200">
            Pricing
          </Link>
          <Link href="/download#verify" className="hover:text-zinc-200">
            Verify a download
          </Link>
        </nav>
      </div>
    </footer>
  );
}
