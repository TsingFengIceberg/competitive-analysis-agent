import type { Metadata } from "next";

import { CompetitionContent } from "./competition-content";

export const metadata: Metadata = {
  title: "CI-Agent 竞品分析",
  icons: { icon: "/logo.png" },
};

export default function CompetitionLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <CompetitionContent>{children}</CompetitionContent>;
}
