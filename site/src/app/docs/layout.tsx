import type { Metadata } from "next";
import { DocsShell } from "@/components/DocsShell";

export const metadata: Metadata = {
  title: { default: "Documentation", template: "%s — Typen docs" },
  description:
    "How the Typen background service and Settings window work, how to customise corrections, and how updates are verified.",
};

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return <DocsShell>{children}</DocsShell>;
}
