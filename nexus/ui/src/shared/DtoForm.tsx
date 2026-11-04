import { useState, type FormEvent } from "react";

// One input per DTO field. "json" fields take a JSON object (e.g. secret values or extra
// config) and are parsed before submit; "number" fields are sent as numbers; empty
// optional fields are left out of the body.
export type Field = {
  name: string;
  label?: string;
  type?: "text" | "password" | "textarea" | "number" | "checkbox" | "select" | "json";
  required?: boolean;
  options?: string[];
  help?: string;
};

type Props = {
  fields: Field[];
  initial?: Record<string, unknown>;
  submitLabel?: string;
  onSubmit: (body: Record<string, unknown>) => void;
  busy?: boolean;
};

function toText(v: unknown, type: Field["type"]) {
  if (v === undefined || v === null) return "";
  if (type === "json") return JSON.stringify(v, null, 2);
  return String(v);
}

export function DtoForm({ fields, initial = {}, submitLabel = "Save", onSubmit, busy }: Props) {
  const [values, setValues] = useState<Record<string, string | boolean>>(() =>
    Object.fromEntries(
      fields.map((f) => [f.name, f.type === "checkbox" ? Boolean(initial[f.name]) : toText(initial[f.name], f.type)]),
    ),
  );
  const [jsonError, setJsonError] = useState<string | null>(null);

  const set = (name: string, v: string | boolean) => setValues((s) => ({ ...s, [name]: v }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body: Record<string, unknown> = {};
    for (const f of fields) {
      const v = values[f.name];
      if (f.type === "checkbox") {
        body[f.name] = v;
        continue;
      }
      if (v === "") continue;
      if (f.type === "number") body[f.name] = Number(v);
      else if (f.type === "json") {
        try {
          body[f.name] = JSON.parse(v as string);
        } catch {
          setJsonError(`${f.label ?? f.name} is not valid JSON`);
          return;
        }
      } else body[f.name] = v;
    }
    setJsonError(null);
    onSubmit(body);
  };

  return (
    <form className="form" onSubmit={submit}>
      {fields.map((f) => (
        <label key={f.name}>
          <span>{f.label ?? f.name}{f.required && " *"}</span>
          {f.type === "checkbox" ? (
            <input type="checkbox" checked={values[f.name] as boolean} onChange={(e) => set(f.name, e.target.checked)} />
          ) : f.type === "select" ? (
            <select value={values[f.name] as string} required={f.required} onChange={(e) => set(f.name, e.target.value)}>
              <option value="">—</option>
              {f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : f.type === "textarea" || f.type === "json" ? (
            <textarea rows={f.type === "json" ? 5 : 3} value={values[f.name] as string} required={f.required}
              onChange={(e) => set(f.name, e.target.value)} />
          ) : (
            <input type={f.type ?? "text"} value={values[f.name] as string} required={f.required}
              onChange={(e) => set(f.name, e.target.value)} />
          )}
          {f.help && <small>{f.help}</small>}
        </label>
      ))}
      {jsonError && <p className="error">{jsonError}</p>}
      <button type="submit" disabled={busy}>{submitLabel}</button>
    </form>
  );
}
