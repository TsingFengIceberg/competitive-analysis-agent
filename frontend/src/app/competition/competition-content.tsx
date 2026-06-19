import { cookies } from "next/headers";

import { CompetitionShell } from "./competition-shell";

function parseSidebarOpenCookie(
  value: string | undefined,
): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

export async function CompetitionContent({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const cookieStore = await cookies();
  const initialSidebarOpen = parseSidebarOpenCookie(
    cookieStore.get("sidebar_state")?.value,
  );

  return <CompetitionShell defaultOpen={initialSidebarOpen}>{children}</CompetitionShell>;
}
