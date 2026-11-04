import { useId, useState, type FormEvent } from "react";

import {
  Button, Checkbox, Field as FormField, Input, NativeSelect, Textarea, fieldErrorId, fieldHintId,
} from "@/ui";
import { shellMessages } from "@/shell/messages";

import { sentence } from "./text";

const m = shellMessages.widgets;

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

export function DtoForm({ fields, initial = {}, submitLabel = m.save, onSubmit, busy }: Props) {
  const [values, setValues] = useState<Record<string, string | boolean>>(() =>
    Object.fromEntries(
      fields.map((f) => [f.name, f.type === "checkbox" ? Boolean(initial[f.name]) : toText(initial[f.name], f.type)]),
    ),
  );
  const [jsonError, setJsonError] = useState<{ name: string; message: string } | null>(null);
  const formId = useId();

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
          setJsonError({ name: f.name, message: m.invalidJson(f.label ?? sentence(f.name)) });
          return;
        }
      } else body[f.name] = v;
    }
    setJsonError(null);
    onSubmit(body);
  };

  return (
    <form className="flex max-w-[520px] flex-col gap-6" onSubmit={submit}>
      {fields.map((f) => {
        const id = `${formId}-${f.name}`;
        const label = f.label ?? sentence(f.name);
        const value = values[f.name];
        if (f.type === "checkbox") {
          return (
            <Checkbox
              key={f.name}
              id={id}
              label={label}
              description={f.help}
              checked={value as boolean}
              onChange={(e) => set(f.name, e.target.checked)}
            />
          );
        }
        const error = jsonError?.name === f.name ? jsonError.message : undefined;
        const control = {
          id,
          value: value as string,
          required: f.required,
          "aria-invalid": error ? true : undefined,
          "aria-describedby": [f.help && fieldHintId(id), error && fieldErrorId(id)].filter(Boolean).join(" ") || undefined,
        };
        return (
          <FormField key={f.name} label={label} htmlFor={id} hint={f.help} required={f.required} error={error}>
            {f.type === "select" ? (
              <NativeSelect {...control} onChange={(e) => set(f.name, e.target.value)}>
                <option value="">{m.choose}</option>
                {f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
              </NativeSelect>
            ) : f.type === "textarea" || f.type === "json" ? (
              <Textarea
                {...control}
                rows={f.type === "json" ? 5 : 3}
                className={f.type === "json" ? "font-mono text-sm" : undefined}
                onChange={(e) => set(f.name, e.target.value)}
              />
            ) : (
              <Input {...control} type={f.type ?? "text"} onChange={(e) => set(f.name, e.target.value)} />
            )}
          </FormField>
        );
      })}
      <Button type="submit" busy={busy} className="self-start">{submitLabel}</Button>
    </form>
  );
}
