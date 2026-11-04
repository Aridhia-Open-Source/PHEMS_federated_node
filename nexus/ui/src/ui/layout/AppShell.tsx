import type { ReactNode } from "react";

import { messages } from "../messages";

export interface AppShellProps {
  header: ReactNode;
  /** Full-width band between the header and the content, e.g. a revalidation ribbon. */
  ribbon?: ReactNode;
  /** Optional section navigation beside the content (not the app menu). */
  sidebar?: ReactNode;
  skipLabel?: string;
  children: ReactNode;
}

/** Page frame: skip link, header, optional ribbon and sidebar, and the main content area. */
export function AppShell({
  header,
  ribbon,
  sidebar,
  skipLabel = messages.skipToContent,
  children,
}: AppShellProps) {
  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-full focus:bg-yellow focus:px-5 focus:py-2 focus:font-semibold focus:text-brand focus:no-underline focus:outline-white"
      >
        {skipLabel}
      </a>
      {header}
      {ribbon}
      <div className="flex flex-1">
        {sidebar ? (
          <aside className="w-65 shrink-0 border-r bg-sidebar text-sidebar-foreground">
            {sidebar}
          </aside>
        ) : null}
        <main
          id="content"
          tabIndex={-1}
          className="min-w-0 flex-1 outline-none"
        >
          <div className="mx-auto w-[96%] px-5 py-10 md:px-10 md:py-16">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
