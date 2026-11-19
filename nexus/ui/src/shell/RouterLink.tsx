import { Link } from "react-router-dom";

import type { RenderNavLink } from "@/ui";

/** Renders a menu item as a router link. `to` is absolute, so it never depends on the current route. */
export const renderLink: RenderNavLink = ({
  item,
  children,
  className,
  onClick,
  "aria-current": current,
}) => (
  <Link to={item.to} className={className} onClick={onClick} aria-current={current}>
    {children}
  </Link>
);
