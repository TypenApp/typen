import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Donate",
  description:
    "Typen is free and open source, with no paid tier. If it saves you time, a donation keeps the lexicon, builds and signing going.",
};

export default function DonateLayout({ children }: { children: React.ReactNode }) {
  return children;
}
