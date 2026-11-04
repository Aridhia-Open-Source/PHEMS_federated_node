import type { ReactNode } from "react";

import type { IconName } from "../icons";

/** One link in a menu. `to` is opaque here: the app decides how to turn it into a link. */
export interface NavItem<TTo extends string = string> {
  id: string;
  label: string;
  to: TTo;
  /** Drawn icon shown beside the label in the menu. */
  icon?: IconName;
  /** Only show this item to members with this role. The app applies the filter. */
  requires?: "owner";
}

export interface NavLinkProps<TTo extends string = string> {
  item: NavItem<TTo>;
  /** Classes that give the link the menu item look, including the active state. */
  className: string;
  active: boolean;
  "aria-current"?: "page";
  /** Runs when the link is followed (the menu uses it to close itself). */
  onClick?: () => void;
  children: ReactNode;
}

/** Renders one link. The app supplies this so `ui` never depends on a router. */
export type RenderNavLink<TTo extends string = string> = (
  props: NavLinkProps<TTo>,
) => ReactNode;
