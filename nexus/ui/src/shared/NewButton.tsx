import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Button, Icon } from "@/ui";

/** The main action of a list page: a link to its create page. */
export function NewButton({ to = "new", children }: { to?: string; children: ReactNode }) {
  return (
    <Button asChild size="lg">
      <Link to={to}>
        {children}
        <Icon name="plus" size="lg" />
      </Link>
    </Button>
  );
}
