import { useId, useState } from "react";

import { Button, Checkbox, ConfirmDialog } from "@/ui";
import { shellMessages } from "@/shell/messages";

import { OwnedBy } from "./owned";

const m = shellMessages.widgets;

type Props = {
  // Name of the thing, shown in the question
  what: string;
  onConfirm: (force: boolean) => void;
  // Shows a "force" checkbox, for endpoints that take ?force=true
  allowForce?: boolean;
  // The verb: on the button and as the question's first word
  label?: string;
  // The consequence, one or two sentences
  description?: string;
  // Who owns the record, when the viewer may not change it: greyed out
  ownedBy?: string | null;
};

export function DeleteButton({ what, onConfirm, allowForce, label = m.delete, description = m.deleteDescription, ownedBy }: Props) {
  const [open, setOpen] = useState(false);
  const [force, setForce] = useState(false);
  const forceId = useId();
  return (
    <>
      <OwnedBy group={ownedBy}>
        <Button type="button" variant="row" size="sm" disabled={!!ownedBy} onClick={() => { setForce(false); setOpen(true); }}>
          {label}
        </Button>
      </OwnedBy>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`${label} ${what}?`}
        description={
          <>
            {description}
            {allowForce && (
              <Checkbox
                id={forceId}
                className="mt-4"
                label={m.force}
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
              />
            )}
          </>
        }
        confirmLabel={label}
        destructive
        onConfirm={() => { setOpen(false); onConfirm(force); }}
      />
    </>
  );
}
