// One resource sub-section: table of the project's resources, assign form (pick from the global list), unassign.
import { useId, useState } from "react";
import { Field as FormField, NativeSelect, SectionHeading } from "@/ui";
import { shellMessages } from "@/shell/messages";
import { ResourceTable, type Column } from "../../shared/ResourceTable";
import { DtoForm, type Field } from "../../shared/DtoForm";
import { DeleteButton } from "../../shared/DeleteButton";
import { EnabledToggle } from "../../shared/EnabledToggle";
import type { Flags } from "../../shared/projectResources";
import { ActivityBadge } from "../../shared/StatusBadge";

const m = shellMessages.widgets;
const t = shellMessages.pages.resources;

export type Option = { value: string; label: string };

type Props<T extends Flags> = {
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

export function ResourceSection<T extends Flags>(p: Props<T>) {
  const pickId = useId();
  const [picked, setPicked] = useState("");
  const [missing, setMissing] = useState(false);
  return (
    <section>
      <ResourceTable<T>
        title={p.title}
        data={p.resources}
        rowKey={p.rowKey}
        columns={[
          ...p.columns,
          { header: "Enabled", cell: (r) => (
            <EnabledToggle hideLabel enabled={r.enabled} onChange={(enabled) => p.onToggle(r, enabled)} />
          ) },
          { header: "Status", cell: (r) => <ActivityBadge flags={r} /> },
          { header: "", cell: (r) => (r.revoked ? null : (
            <DeleteButton label={m.unassign} description={m.unassignDescription} what={p.name(r)}
              onConfirm={() => p.onUnassign(r)} />
          )) },
        ]}
      />
      <SectionHeading level={3}>{t.assign(p.title)}</SectionHeading>
      {p.help && <p className="mb-6 max-w-[72ch] text-ink-3">{p.help}</p>}
      <div className="flex max-w-[520px] flex-col gap-6">
        <FormField label={p.pickLabel} htmlFor={pickId} required error={missing ? t.pickFirst : undefined}>
          <NativeSelect
            id={pickId}
            value={picked}
            aria-invalid={missing || undefined}
            onChange={(e) => { setPicked(e.target.value); setMissing(false); }}
          >
            <option value="">{m.choose}</option>
            {p.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </NativeSelect>
        </FormField>
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
