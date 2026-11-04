import type { ReactNode } from "react";

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../components/alert-dialog";
import { Icon, type IconName } from "../icons";
import { Button } from "../components/button";
import { messages } from "../messages";

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Can hold emphasis, e.g. the name of what is being removed in bold. */
  description: ReactNode;
  /** Sits left of the title and matches the action. */
  icon?: IconName;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Style the confirm button as a destructive action. */
  destructive?: boolean;
  /** Disables the buttons while the action runs. */
  pending?: boolean;
  /** Shown inside the dialog, e.g. why the action failed. */
  error?: ReactNode;
  /** The dialog stays open until the caller closes it. */
  onConfirm: () => void;
}

/** Asks "are you sure?" before an action that cannot be undone. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  icon,
  confirmLabel = messages.confirm,
  cancelLabel = messages.cancel,
  destructive,
  pending,
  error,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {icon ? <Icon name={icon} size="xl" /> : null}
            {title}
          </AlertDialogTitle>
          {/* A div, so the description may hold block content. */}
          <AlertDialogDescription asChild>
            <div className="text-ink">{description}</div>
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error ? (
          <p role="alert" className="text-sm font-semibold text-destructive">
            {error}
          </p>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>
            {cancelLabel}
          </AlertDialogCancel>
          <Button
            type="button"
            variant={destructive ? "destructive" : "default"}
            disabled={pending}
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
