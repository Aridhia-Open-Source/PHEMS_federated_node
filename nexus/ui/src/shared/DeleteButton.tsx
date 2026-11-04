import { useState } from "react";

type Props = {
  what: string;
  onConfirm: (force: boolean) => void;
  // Shows a "force" checkbox, for endpoints that take ?force=true
  allowForce?: boolean;
  label?: string;
};

export function DeleteButton({ what, onConfirm, allowForce, label = "Delete" }: Props) {
  const [open, setOpen] = useState(false);
  const [force, setForce] = useState(false);
  if (!open) return <button className="danger" onClick={() => setOpen(true)}>{label}</button>;
  return (
    <span className="confirm" role="dialog">
      {label} {what}?
      {allowForce && (
        <label>
          <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> force
        </label>
      )}
      <button className="danger" onClick={() => { setOpen(false); onConfirm(force); }}>Yes</button>
      <button onClick={() => setOpen(false)}>No</button>
    </span>
  );
}
