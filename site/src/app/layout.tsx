import type { Metadata } from "next";
import { Courier_Prime } from "next/font/google";
import "./globals.css";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";

const typewriter = Courier_Prime({
  subsets: ["latin"],
  weight: ["400", "700"],
  style: ["normal", "italic"],
  display: "swap",
  variable: "--font-typewriter",
});

export const metadata: Metadata = {
  title: "AutoCorrect Desktop — system-wide offline autocorrect",
  description:
    "Offline, system-wide autocorrect for Windows. Fixes typos, homophones and punctuation in every app with sub-millisecond latency. Public beta.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`dark ${typewriter.variable}`}>
      <body className="flex min-h-screen flex-col bg-zinc-950 font-sans text-zinc-200 antialiased selection:bg-blue-600/60 selection:text-white">
        <Navbar />
        <main className="flex-1">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
