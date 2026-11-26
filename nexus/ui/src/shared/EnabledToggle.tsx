import { useId } from "react";

import { Toggle } from "@/ui";
import { shellMessages } from "@/shell/messages";

import { OwnedBy } from "./owned";

type Props = {
  enabled: boolean;
  onChange: (next: boolean) => void;
  busy?: boolean;
  // In a column headed "Enabled": the label is still read out, not shown
  hideLabel?: boolean;
  // Who owns the record, when the viewer may not change it: greyed out
  ownedBy?: string | null;
};

export function EnabledToggle({ enabled, onChange, busy, hideLabel, ownedBy }: Props) {
  const id = useId();
  const label = shellMessages.widgets.enabled;
  return (
    <OwnedBy group={ownedBy}>
    <Toggle
      id={id}
      label={hideLabel ? <span className="sr-only">{label}</span> : label}
      className="justify-start"
      checked={enabled}
      disabled={busy || !!ownedBy}
      onChange={(e) => onChange(e.target.checked)}
    />
    </OwnedBy>
  );
}
