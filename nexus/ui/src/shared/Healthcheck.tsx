import { Button, SectionHeading } from "@/ui";
import { shellMessages } from "@/shell/messages";

import { Json } from "./Json";

const m = shellMessages.widgets.healthcheck;

// The healthcheck part of a detail page: a button that runs the check (a query with
// enabled: false) and the response once it is in.
type Props = {
  query: { data: unknown; isFetching: boolean; refetch: () => unknown };
  level?: 2 | 3;
};

export function Healthcheck({ query, level = 2 }: Props) {
  return (
    <>
      <SectionHeading level={level}>{m.title}</SectionHeading>
      <Button variant="secondary" busy={query.isFetching} onClick={() => query.refetch()}>
        {m.run}
      </Button>
      {query.data !== undefined && <div className="mt-6"><Json value={query.data} /></div>}
    </>
  );
}
