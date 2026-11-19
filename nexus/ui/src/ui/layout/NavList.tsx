import { Icon } from "../icons";
import type { NavItem, RenderNavLink } from "./types";
import { menuLinkClass } from "./SideMenu";

export interface NavListProps<TTo extends string = string> {
  items: readonly NavItem<TTo>[];
  /** `id` of the item for the current page. */
  activeId?: string;
  renderLink: RenderNavLink<TTo>;
  /** Accessible name for the navigation landmark. */
  label: string;
  onNavigate?: () => void;
}

/** A list of links. How each link is built is left to `renderLink`, so no router is needed here. */
export function NavList<TTo extends string = string>({
  items,
  activeId,
  renderLink,
  label,
  onNavigate,
}: NavListProps<TTo>) {
  return (
    <nav aria-label={label}>
      <ul className="flex flex-col">
        {items.map((item) => {
          const active = item.id === activeId;
          return (
            <li
              key={item.id}
              className="border-b border-white/20 last:border-b-0"
            >
              {renderLink({
                item,
                active,
                className: menuLinkClass({ active }),
                "aria-current": active ? "page" : undefined,
                onClick: onNavigate,
                children: (
                  <>
                    {item.icon ? (
                      <Icon
                        name={item.icon}
                        size="lg"
                        className="text-yellow"
                      />
                    ) : null}
                    {item.label}
                  </>
                ),
              })}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
