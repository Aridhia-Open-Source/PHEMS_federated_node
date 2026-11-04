import { Link } from "react-router-dom";

import { Button, Icon } from "@/ui";
import { shellMessages } from "@/shell/messages";

/** The way back to the list a page came from. `what` is that list's name in lower case, e.g. "secrets". */
export function BackLink({ to, what }: { to: string; what: string }) {
  return (
    <div className="mb-6">
      <Button asChild variant="secondary" size="sm">
        <Link to={to}>
          <Icon name="back" size="sm" />
          {shellMessages.widgets.backTo(what)}
        </Link>
      </Button>
    </div>
  );
}
