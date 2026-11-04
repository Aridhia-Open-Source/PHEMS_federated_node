import type { IconName, NavItem } from "@/ui";
import { pages } from "@/routes";

import { shellMessages } from "./messages";

// Menu entries come from the page registry in routes.tsx, so a new page shows up here
// without touching this file; add an icon below if it should have one.
const icons: Record<string, IconName> = {
  projects: "orgChart",
  "global/secrets": "lock",
  "global/providers": "switch",
  "global/repositories/triggers": "transfer",
  "global/repositories/results": "save",
  "global/datasets": "file",
};

const toItem = (p: (typeof pages)[number]): NavItem => ({
  id: p.path,
  label: p.label,
  to: `/${p.path}`,
  icon: icons[p.path],
});

export const navGroups = [
  {
    label: shellMessages.navGroups.projects,
    items: pages.filter((p) => !p.path.startsWith("global/")).map(toItem),
  },
  {
    label: shellMessages.navGroups.global,
    items: pages.filter((p) => p.path.startsWith("global/")).map(toItem),
  },
];

/** The item whose page the visitor is on (a page below an item's path counts too). */
export function activeNavId(pathname: string): string | undefined {
  return navGroups
    .flatMap((g) => g.items)
    .find((item) => pathname === item.to || pathname.startsWith(`${item.to}/`))?.id;
}
