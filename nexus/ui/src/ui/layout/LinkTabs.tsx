import { cn } from "../lib/utils";
import type { NavItem, RenderNavLink } from "./types";

export interface LinkTabsProps<TTo extends string = string> {
  items: readonly NavItem<TTo>[];
  /** `id` of the item for the current page. */
  activeId: string;
  renderLink: RenderNavLink<TTo>;
  /** Accessible name for the navigation landmark. */
  label: string;
}

/** Tabs that are links, for sections of a page that have their own address. The active tab is a blue tab. */
export function LinkTabs<TTo extends string = string>({
  items,
  activeId,
  renderLink,
  label,
}: LinkTabsProps<TTo>) {
  return (
    <nav aria-label={label} className="mb-8">
      <ul className="flex flex-wrap items-end gap-1 border-b-2 border-brand">
        {items.map((item) => {
          const active = item.id === activeId;
          return (
            <li key={item.id}>
              {renderLink({
                item,
                active,
                className: cn(
                  "inline-flex items-center rounded-t-[10px] px-6 py-3 text-[1.05em] whitespace-nowrap transition-colors",
                  active
                    ? "bg-brand font-bold text-white"
                    : "bg-blue-tint-95 font-medium text-blue hover:bg-blue-tint-90",
                ),
                "aria-current": active ? "page" : undefined,
                children: item.label,
              })}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
