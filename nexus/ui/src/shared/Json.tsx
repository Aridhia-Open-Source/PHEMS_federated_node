import { CodeBlock } from "@/ui";
import { shellMessages } from "@/shell/messages";

// Read-only dump of a record, for detail views and healthchecks.
export function Json({ value }: { value: unknown }) {
  return <CodeBlock label={shellMessages.widgets.jsonLabel} text={JSON.stringify(value, null, 2)} />;
}
