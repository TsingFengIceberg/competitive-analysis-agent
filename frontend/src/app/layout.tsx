import "@/styles/globals.css";
import { type Metadata } from "next";

import { ThemeProvider } from "@/components/theme-provider";

export const metadata: Metadata = {
  title: "CI-Agent — AI 驱动的竞品分析 Agent 协作系统",
  description:
    "基于 LangGraph 的多 Agent 协作竞品分析系统，支持自动采集、多维对比、质量审查、交互式报告生成。",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressContentEditableWarning suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" enableSystem disableTransitionOnChange>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
