// One link sub-section: table of current links, add form (pick from the global list), unlink.
import { useState } from "react";
import { ResourceTable, type Column } from "../../shared/ResourceTable";
import { DtoForm, type Field } from "../../shared/DtoForm";
import { DeleteButton } from "../../shared/DeleteButton";
import { EnabledToggle } from "../../shared/EnabledToggle";

type LinkFlags = { enabled?: boolean; revoked?: boolean; active?: boolean };
export type Option = { value: string; label: string };

type Props<T extends LinkFlags> = {
  title: string;
  links: T[] | undefined;
  rowKey: (l: T) => string | number;
  name: (l: T) => string;
  columns: Column<T>[];
  // The global list to pick from
  options: Option[] | undefined;
  pickLabel: string;
  fields: Field[];
  initial?: Record<string, unknown>;
  onAdd: (picked: string, body: Record<string, unknown>) => void;
  busy: boolean;
  onToggle: (l: T, enabled: boolean) => void;
  onUnlink: (l: T) => void;
  help?: string;
};

export function LinkSection<T extends LinkFlags>(p: Props<T>) {
  const [picked, setPicked] = useState("");
  const [missing, setMissing] = useState(false);
  return (
    <section>
      <h2>{p.title}</h2>
      <ResourceTable<T>
        data={p.links}
        rowKey={p.rowKey}
        columns={[
          ...p.columns,
          { header: "Enabled", cell: (l) => (
            <EnabledToggle enabled={!!l.enabled} onChange={(enabled) => p.onToggle(l, enabled)} />
          ) },
          { header: "Status", cell: (l) => (l.revoked ? "revoked" : l.active ? "active" : "inactive") },
          { header: "", cell: (l) => (l.revoked ? null : (
            <DeleteButton label="Unlink" what={p.name(l)} onConfirm={() => p.onUnlink(l)} />
          )) },
        ]}
      />
      <h3>Add {p.title.toLowerCase()}</h3>
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
          submitLabel="Link"
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
