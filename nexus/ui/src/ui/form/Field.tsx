import type { ReactNode } from "react";

import { FormMessage } from "../components/form-message";
import type { FieldTone } from "../components/input";
import { Label } from "../components/label";
import { Icon } from "../icons";
import { cn } from "../lib/utils";
import { messages } from "../messages";

export interface FieldProps {
  label: string;
  /**
   * Id of the input the label is for. Leave it out for a group of inputs (a list, a pair of
   * inputs, radio buttons): the field is then a fieldset and the label its legend.
   */
  htmlFor?: string;
  /** Id for the wrapper, so other parts of a page can link to this field or focus it. */
  anchorId?: string;
  hint?: string;
  /** Marks the field as required: a star beside the label plus text for screen readers. */
  required?: boolean;
  /** Message shown under the field; pass `fieldErrorId(htmlFor)` to the input's aria-describedby. */
  error?: string;
  /** Id of the error text. Defaults to `fieldErrorId(htmlFor ?? anchorId)`. */
  errorId?: string;
  /** `onBlue` for fields on a blue surface: white label, yellow star, pink error. */
  tone?: FieldTone;
  className?: string;
  children: ReactNode;
}

/** Id of the error text for a field, for the input's `aria-describedby`. */
export function fieldErrorId(id: string): string {
  return `${id}-error`;
}

/** Id of the hint text for a field. */
export function fieldHintId(id: string): string {
  return `${id}-hint`;
}

function RequiredMark({
  invalid,
  onBlue,
}: {
  invalid: boolean;
  onBlue: boolean;
}) {
  return (
    <>
      <span
        data-slot="required-star"
        aria-hidden="true"
        className={cn(
          "inline-flex",
          invalid
            ? onBlue
              ? "text-error"
              : "text-destructive"
            : onBlue
              ? "text-yellow"
              : "text-required",
        )}
      >
        <Icon
          name="star"
          className="size-3"
          style={{ width: 12, height: 12 }}
        />
      </span>
      <span className="sr-only">{messages.required}</span>
    </>
  );
}

/** A labelled form field with an optional hint and error message. Works with any form library. */
export function Field({
  label,
  htmlFor,
  anchorId,
  hint,
  required,
  error,
  errorId,
  tone = "onWhite",
  className,
  children,
}: FieldProps) {
  const onBlue = tone === "onBlue";
  const baseId = htmlFor ?? anchorId ?? label.replace(/\s+/g, "-");
  const errId = errorId ?? fieldErrorId(baseId);
  const hintId = fieldHintId(baseId);
  const labelContent = (
    <>
      {label}
      {required ? <RequiredMark invalid={!!error} onBlue={onBlue} /> : null}
    </>
  );
  const body = (
    <>
      {hint ? (
        <p
          id={hintId}
          className={cn(
            "flex items-start gap-2 text-[0.88em] leading-snug font-medium",
            onBlue ? "text-white" : "text-blue-hint",
          )}
        >
          <Icon
            name="info"
            className="size-4"
            style={{ width: 16, height: 16 }}
          />
          <span>{hint}</span>
        </p>
      ) : null}
      {children}
      {error ? (
        <FormMessage id={errId} className={onBlue ? "text-error" : undefined}>
          {error}
        </FormMessage>
      ) : null}
    </>
  );
  const classes = cn("flex scroll-mt-24 flex-col gap-2", className);
  const labelClass = onBlue ? "text-white" : undefined;

  if (htmlFor) {
    return (
      <div
        id={anchorId}
        tabIndex={anchorId ? -1 : undefined}
        data-tone={tone}
        className={classes}
      >
        <Label htmlFor={htmlFor} className={labelClass}>
          {labelContent}
        </Label>
        {body}
      </div>
    );
  }
  return (
    <fieldset
      id={anchorId}
      tabIndex={anchorId ? -1 : undefined}
      data-tone={tone}
      aria-describedby={error ? errId : undefined}
      className={classes}
    >
      <legend
        className={cn(
          "mb-2 flex items-center gap-2 text-[0.95em] leading-snug font-semibold",
          onBlue ? "text-white" : "text-foreground",
        )}
      >
        {labelContent}
      </legend>
      {body}
    </fieldset>
  );
}
