import { Button } from "@/ui";
import { shellMessages } from "@/shell/messages";

import { DeleteButton } from "./DeleteButton";

const m = shellMessages.widgets;

// Revoking a global resource withdraws it from every project at once; restoring undoes that.
// Both are PATCH { revoked } on the global resource, so the caller only says which way.
export function RevokeButton({ revoked, what, onChange }: { revoked: boolean; what: string; onChange: (revoked: boolean) => void }) {
  if (revoked) return <Button type="button" variant="row" size="sm" onClick={() => onChange(false)}>{m.restore}</Button>;
  return <DeleteButton label={m.revoke} description={m.revokeDescription} what={what} onConfirm={() => onChange(true)} />;
}
