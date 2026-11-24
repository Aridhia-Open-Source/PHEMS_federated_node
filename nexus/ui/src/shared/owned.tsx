// Greys out the edit, delete and revoke controls of a record the viewer may not change, with a tooltip
// naming why. Owner groups are gone and the grants that replace them (ADR 0037) are not built, so every
// control is allowed.
import type { ReactNode } from "react";

import { shellMessages } from "@/shell/messages";

// Why the viewer may not change the record, else null: always null until grants decide it
export function ownedBy(_record: unknown, _groups: Set<string>): string | null {
  return null;
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
