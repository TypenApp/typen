import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Perpetual Standard and Pro licences for AutoCorrect Desktop with 12 months of updates. Every download starts with a free 14-day Pro trial.",
};

export default function PricingLayout({ children }: { children: React.ReactNode }) {
  return children;
}
