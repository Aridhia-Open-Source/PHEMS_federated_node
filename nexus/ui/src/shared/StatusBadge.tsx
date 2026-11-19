import type { ComponentProps } from "react";

import { Badge, Icon, type IconName } from "@/ui";
import { shellMessages } from "@/shell/messages";

import type { Flags } from "./projectResources";
import { sentence } from "./text";

type Variant = NonNullable<ComponentProps<typeof Badge>["variant"]>;

// Task and result states, trigger states, health statuses and the flags of a resource.
// Anything else (a state added later) shows as a plain pill.
const variants: Record<string, Variant> = {
  success: "success", yielded: "success", delivered: "success", ok: "success", enabled: "success", active: "success",
  failed: "destructive", rejected: "destructive", revoked: "destructive", error: "destructive",
  unauthorized: "destructive", not_found: "destructive", unreachable: "destructive", secret_missing: "destructive",
  canceled: "warning",
  queued: "info", running: "info", in_progress: "info",
};

// Colour is never the only signal: the pill says the state in words, and these icons back it up.
const icons: Partial<Record<Variant, IconName>> = {
  success: "tick", destructive: "warning", warning: "warning", info: "info",
};

/** A state as a pill: green for done and healthy, pink for failed, amber for stopped, blue for under way. */
export function StatusBadge({ status }: { status: string }) {
  const key = status.toLowerCase();
  const variant = variants[key] ?? "secondary";
  const icon = icons[variant];
  return (
    <Badge variant={variant}>
      {icon && <Icon name={icon} size="xs" />}
      {key === "ok" ? shellMessages.widgets.statusOk : sentence(status)}
    </Badge>
  );
}

/** A project resource's flags: enabled or not, then revoked, active or inactive. */
export function StateBadges({ flags }: { flags: Flags }) {
  return (
    <span className="flex flex-wrap gap-2">
      <StatusBadge status={flags.enabled ? "enabled" : "disabled"} />
      <ActivityBadge flags={flags} />
    </span>
  );
}

/** Revoked, active or inactive. */
export function ActivityBadge({ flags }: { flags: Flags }) {
  return <StatusBadge status={flags.revoked ? "revoked" : flags.active ? "active" : "inactive"} />;
}
