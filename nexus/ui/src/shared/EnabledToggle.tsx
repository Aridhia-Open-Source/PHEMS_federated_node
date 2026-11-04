import { useId } from "react";

import { Toggle } from "@/ui";
import { shellMessages } from "@/shell/messages";

type Props = {
  enabled: boolean;
  onChange: (next: boolean) => void;
  busy?: boolean;
  // In a column headed "Enabled": the label is still read out, not shown
  hideLabel?: boolean;
};

export function EnabledToggle({ enabled, onChange, busy, hideLabel }: Props) {
  const id = useId();
  const label = shellMessages.widgets.enabled;
  return (
    <Toggle
      id={id}
      label={hideLabel ? <span className="sr-only">{label}</span> : label}
      className="justify-start"
      checked={enabled}
      disabled={busy}
      onChange={(e) => onChange(e.target.checked)}
    />
  );
}
