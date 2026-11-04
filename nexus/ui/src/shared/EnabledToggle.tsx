type Props = { enabled: boolean; onChange: (next: boolean) => void; busy?: boolean };

export function EnabledToggle({ enabled, onChange, busy }: Props) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={enabled} disabled={busy} onChange={(e) => onChange(e.target.checked)} />
      {enabled ? "enabled" : "disabled"}
    </label>
  );
}
