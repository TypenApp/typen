import type { Metadata } from "next";
import { DocsShell } from "@/components/DocsShell";

export const metadata: Metadata = {
  title: { default: "Documentation", template: "%s — AutoCorrect docs" },
  description:
    "How the AutoCorrect background service and Settings window work, how to customise corrections, and how licensing and updates are handled.",
};

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return <DocsShell>{children}</DocsShell>;
}
