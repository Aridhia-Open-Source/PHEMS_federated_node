// One resource sub-section: table of the project's resources, assign form (pick from the global list), unassign.
import { useState } from "react";
import { ResourceTable, type Column } from "../../shared/ResourceTable";
import { DtoForm, type Field } from "../../shared/DtoForm";
import { DeleteButton } from "../../shared/DeleteButton";
import { EnabledToggle } from "../../shared/EnabledToggle";

type ResourceFlags = { enabled?: boolean; revoked?: boolean; active?: boolean };
export type Option = { value: string; label: string };

type Props<T extends ResourceFlags> = {
  title: string;
  resources: T[] | undefined;
  rowKey: (r: T) => string | number;
  name: (r: T) => string;
  columns: Column<T>[];
  // The global list to pick from
  options: Option[] | undefined;
  pickLabel: string;
  fields: Field[];
  initial?: Record<string, unknown>;
  onAdd: (picked: string, body: Record<string, unknown>) => void;
  busy: boolean;
  onToggle: (r: T, enabled: boolean) => void;
  onUnassign: (r: T) => void;
  help?: string;
};

export function ResourceSection<T extends ResourceFlags>(p: Props<T>) {
  const [picked, setPicked] = useState("");
  const [missing, setMissing] = useState(false);
  return (
    <section>
      <h2>{p.title}</h2>
      <ResourceTable<T>
        data={p.resources}
        rowKey={p.rowKey}
        columns={[
          ...p.columns,
          { header: "Enabled", cell: (r) => (
            <EnabledToggle enabled={!!r.enabled} onChange={(enabled) => p.onToggle(r, enabled)} />
          ) },
          { header: "Status", cell: (r) => (r.revoked ? "revoked" : r.active ? "active" : "inactive") },
          { header: "", cell: (r) => (r.revoked ? null : (
            <DeleteButton label="Unassign" what={p.name(r)} onConfirm={() => p.onUnassign(r)} />
          )) },
        ]}
      />
      <h3>Assign {p.title.toLowerCase()}</h3>
      {p.help && <p><small>{p.help}</small></p>}
      <div className="form">
        <label>
          <span>{p.pickLabel} *</span>
          <select value={picked} onChange={(e) => { setPicked(e.target.value); setMissing(false); }}>
            <option value="">—</option>
            {p.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        {missing && <p className="error">Pick one from the list first</p>}
        <DtoForm
          fields={p.fields}
          initial={p.initial}
          submitLabel="Assign"
          busy={p.busy}
          onSubmit={(body) => {
            if (!picked) return setMissing(true);
            p.onAdd(picked, body);
          }}
        />
      </div>
    </section>
  );
}
