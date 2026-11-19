import { useRef, type ComponentProps, type ReactNode } from "react";
import { Dialog } from "radix-ui";

import { Button } from "../components/button";
import { Icon } from "../icons";
import { cn } from "../lib/utils";
import { messages } from "../messages";

export interface SideMenuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  /** Shown at the top in yellow, e.g. the current organisation. */
  description?: string;
  closeLabel?: string;
  /** Small content at the foot of the panel, e.g. a status line. */
  footer?: ReactNode;
  children: ReactNode;
}

/** Blue panel that slides in from the right. Closes on Esc, overlay click and the close button. */
export function SideMenu({
  open,
  onOpenChange,
  title = messages.menuTitle,
  description,
  closeLabel = messages.closeMenu,
  footer,
  children,
}: SideMenuProps) {
  // The menu is opened from outside (no Dialog.Trigger), so remember the opener to give focus back.
  const opener = useRef<HTMLElement | null>(null);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim duration-(--motion-enter) ease-(--ease-out) data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content
          data-surface="blue"
          onOpenAutoFocus={() => {
            opener.current = document.activeElement as HTMLElement | null;
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            opener.current?.focus();
          }}
          // Radix wants a description; opt out explicitly when there is none.
          {...(description ? {} : { "aria-describedby": undefined })}
          className="fixed inset-y-0 right-0 z-50 flex w-[400px] max-w-full flex-col bg-brand text-white outline-none duration-(--motion-enter) ease-(--ease-out) data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right data-[state=open]:animate-in data-[state=open]:slide-in-from-right max-md:w-full"
        >
          <div className="flex items-start justify-between gap-4 px-8 pt-8 pb-4">
            <div className="min-w-0 pt-2">
              <Dialog.Title className="sr-only">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="font-semibold text-yellow">
                  {description}
                </Dialog.Description>
              ) : null}
            </div>
            <Dialog.Close asChild>
              <Button
                type="button"
                variant="icon"
                size="icon"
                onBlue
                aria-label={closeLabel}
              >
                <Icon name="close" size="sm" />
              </Button>
            </Dialog.Close>
          </div>
          <div className="flex flex-1 flex-col gap-6 overflow-y-auto px-8 py-4">
            {children}
          </div>
          <div className="flex items-end justify-between gap-4 px-8 pt-4 pb-6">
            <div className="min-w-0 text-sm">{footer}</div>
            <Icon name="star" size="lg" className="shrink-0 text-yellow" />
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** A link in the blue panel: white, turning yellow on hover, with room for an icon. */
export function menuLinkClass({ active = false }: { active?: boolean } = {}) {
  return cn(
    "flex w-full items-center gap-3 py-4 text-left text-[1.05em] font-semibold no-underline transition-colors hover:text-yellow",
    active ? "text-yellow" : "text-white",
  );
}

export function menuItemClass({
  active = false,
  danger = false,
}: { active?: boolean; danger?: boolean } = {}) {
  return cn(
    "flex w-full items-center gap-3 rounded-field px-4 py-3 text-left text-sm font-medium transition-colors",
    danger
      ? "text-destructive hover:bg-destructive/10"
      : "hover:bg-accent hover:text-accent-foreground",
    active && !danger && "bg-accent text-accent-foreground",
  );
}

/** A menu entry that runs an action rather than going to a page. */
export function SideMenuItem({
  className,
  ...props
}: ComponentProps<"button">) {
  return (
    <button
      type="button"
      className={cn(menuLinkClass(), className)}
      {...props}
    />
  );
}

export function SideMenuDivider() {
  return <hr className="border-white/20" />;
}
