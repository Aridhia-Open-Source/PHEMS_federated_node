// A record owned by a group the viewer is not in (ADR 0036): nexus-api refuses every change to it with a
// 409, so its edit, delete and revoke controls are greyed out, with a tooltip naming the group.
import type { ReactNode } from "react";

import { shellMessages } from "@/shell/messages";

// The record's owner group when the viewer is not in it, else null
export function ownedBy(record: { owner_group?: string | null } | undefined, groups: Set<string>): string | null {
  const group = record?.owner_group;
  return group && !groups.has(group) ? group : null;
}

// Wraps a greyed-out control: a disabled button gets no pointer events, so the tooltip sits on the wrapper
export function OwnedBy({ group, children }: { group?: string | null; children: ReactNode }) {
  if (!group) return <>{children}</>;
  return (
    <span title={shellMessages.widgets.ownedBy(group)} className="inline-flex cursor-not-allowed">
      {children}
    </span>
  );
}
