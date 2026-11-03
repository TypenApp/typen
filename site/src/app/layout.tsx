import type { Metadata } from "next";
import { Inter, Instrument_Serif, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { FULL_VERSION } from "@/data/releases";

const sans = Inter({ subsets: ["latin"], display: "swap", variable: "--font-sans" });
const display = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  display: "swap",
  variable: "--font-display",
});
const mono = JetBrains_Mono({ subsets: ["latin"], display: "swap", variable: "--font-mono" });

const SITE_URL = "https://autocorrect-desktop.vercel.app";
const DESCRIPTION =
  "AutoCorrect is a small background service that fixes typos, homophones and punctuation in every application as you type. Offline, under a millisecond per keystroke, for Windows, macOS and Linux.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "AutoCorrect — system-wide autocorrect, offline",
    template: "%s — AutoCorrect",
  },
  description: DESCRIPTION,
  applicationName: "AutoCorrect Desktop",
  keywords: ["autocorrect", "spell check", "typing", "desktop", "offline", "Windows", "macOS", "Linux"],
  openGraph: {
    type: "website",
    siteName: "AutoCorrect",
    title: "AutoCorrect — system-wide autocorrect, offline",
    description: DESCRIPTION,
    url: SITE_URL,
  },
  twitter: { card: "summary", title: "AutoCorrect", description: DESCRIPTION },
  other: { "x-autocorrect-version": FULL_VERSION },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable} ${mono.variable}`}>
      <body className="flex min-h-screen flex-col antialiased">
        <Navbar />
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
