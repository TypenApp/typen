import type { Metadata } from "next";
import { Syne, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { FULL_VERSION } from "@/data/releases";

// Syne is a variable font: one file covers 400–800, used for both display and UI text.
const sans = Syne({ subsets: ["latin"], display: "swap", variable: "--font-sans" });
const mono = JetBrains_Mono({ subsets: ["latin"], display: "swap", variable: "--font-mono" });

const SITE_URL = "https://autocorrect-desktop.vercel.app";
const DESCRIPTION =
  "Tact is a small background service that fixes typos, homophones and punctuation in every application as you type. Offline, under a millisecond per keystroke, free and open source, for Windows, macOS and Linux.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Tact — system-wide autocorrect, offline and open source",
    template: "%s — Tact",
  },
  description: DESCRIPTION,
  applicationName: "Tact",
  keywords: ["autocorrect", "spell check", "typing", "desktop", "offline", "open source", "Windows", "macOS", "Linux"],
  openGraph: {
    type: "website",
    siteName: "Tact",
    title: "Tact — system-wide autocorrect, offline and open source",
    description: DESCRIPTION,
    url: SITE_URL,
  },
  twitter: { card: "summary", title: "Tact", description: DESCRIPTION },
  other: { "x-tact-version": FULL_VERSION },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body className="flex min-h-screen flex-col antialiased">
        <Navbar />
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
