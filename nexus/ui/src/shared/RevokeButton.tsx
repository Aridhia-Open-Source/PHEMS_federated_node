import { DeleteButton } from "./DeleteButton";

// Revoking a global resource withdraws it from every project at once; restoring undoes that.
// Both are PATCH { revoked } on the global resource, so the caller only says which way.
export function RevokeButton({ revoked, what, onChange }: { revoked: boolean; what: string; onChange: (revoked: boolean) => void }) {
  if (revoked) return <button onClick={() => onChange(false)}>Restore</button>;
  return <DeleteButton label="Revoke" what={what} onConfirm={() => onChange(true)} />;
}
