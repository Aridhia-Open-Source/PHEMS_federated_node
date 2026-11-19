import { Button } from "@/ui";
import { shellMessages } from "@/shell/messages";

import { DeleteButton } from "./DeleteButton";
import { OwnedBy } from "./owned";

const m = shellMessages.widgets;

// Revoking a global resource withdraws it from every project at once; restoring undoes that.
// Both are PATCH { revoked } on the global resource, so the caller only says which way.
type Props = {
  revoked: boolean;
  what: string;
  onChange: (revoked: boolean) => void;
  // The owner group, when the viewer is not in it: greyed out
  ownedBy?: string | null;
};

export function RevokeButton({ revoked, what, onChange, ownedBy }: Props) {
  if (revoked) {
    return (
      <OwnedBy group={ownedBy}>
        <Button type="button" variant="row" size="sm" disabled={!!ownedBy} onClick={() => onChange(false)}>{m.restore}</Button>
      </OwnedBy>
    );
  }
  return <DeleteButton label={m.revoke} description={m.revokeDescription} what={what} ownedBy={ownedBy} onConfirm={() => onChange(true)} />;
}
