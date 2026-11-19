import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { Icon, type IconName } from "../icons";
import { messages } from "../messages";

export type ToastTone = "success" | "info" | "warning" | "error";

export interface ToastOptions {
  tone?: ToastTone;
  message: ReactNode;
  /** An optional follow-up such as "Try again". Dismisses the toast once pressed. */
  action?: { label: string; onClick: () => void };
}

interface ToastEntry extends ToastOptions {
  id: number;
  tone: ToastTone;
}

interface ToastApi {
  /** Shows a toast and returns its id. */
  show: (options: ToastOptions) => number;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export const MAX_TOASTS = 3;
export const TOAST_DURATION_MS = 5000;

const icons: Record<ToastTone, IconName> = {
  success: "tick",
  info: "info",
  warning: "warning",
  error: "star",
};

// Shades that stay readable on the blue card.
const iconColours: Record<ToastTone, string> = {
  success: "text-success",
  info: "text-info",
  warning: "text-warning",
  error: "text-error",
};

/** Warnings and errors need a decision or a retry, so they stay until dismissed. */
const sticky = (tone: ToastTone) => tone === "warning" || tone === "error";

function ToastItem({
  toast,
  onDismiss,
}: {
  toast: ToastEntry;
  onDismiss: (id: number) => void;
}) {
  const [paused, setPaused] = useState(false);
  const remaining = useRef(TOAST_DURATION_MS);
  const { id, tone } = toast;

  useEffect(() => {
    if (sticky(tone) || paused) return;
    const startedAt = Date.now();
    const timer = setTimeout(() => onDismiss(id), remaining.current);
    return () => {
      clearTimeout(timer);
      remaining.current = Math.max(
        0,
        remaining.current - (Date.now() - startedAt),
      );
    };
  }, [id, tone, paused, onDismiss]);

  return (
    <div
      data-slot="toast"
      data-tone={tone}
      data-surface="blue"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
      className="pointer-events-auto flex w-full items-start gap-3 rounded-card bg-brand px-4 py-3 font-semibold text-white shadow-overlay duration-(--motion-enter) ease-(--ease-out) animate-in fade-in-0 slide-in-from-bottom-2 motion-reduce:animate-none"
    >
      <Icon
        name={icons[tone]}
        className={`mt-0.5 ${iconColours[tone]}`}
        style={{ width: 22, height: 22 }}
      />
      <div className="min-w-0 flex-1">
        <div>{toast.message}</div>
        {toast.action ? (
          <button
            type="button"
            className="mt-1 font-semibold text-yellow underline-offset-4 hover:underline"
            onClick={() => {
              toast.action?.onClick();
              onDismiss(id);
            }}
          >
            {toast.action.label}
          </button>
        ) : null}
      </div>
      <button
        type="button"
        aria-label={messages.feedback.dismiss}
        className="-m-1 rounded-full p-1 text-white hover:bg-white/15"
        onClick={() => onDismiss(id)}
      >
        <Icon name="close" size="sm" />
      </button>
    </div>
  );
}

/** Holds the toast stack. Mount once near the root of the app. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const show = useCallback((options: ToastOptions) => {
    const id = nextId.current++;
    const entry: ToastEntry = { ...options, id, tone: options.tone ?? "info" };
    // Newest at the bottom; the oldest makes room once there are too many.
    setToasts((current) => [...current, entry].slice(-MAX_TOASTS));
    return id;
  }, []);

  const api = useMemo(() => ({ show, dismiss }), [show, dismiss]);

  const polite = toasts.filter((t) => !sticky(t.tone));
  const assertive = toasts.filter((t) => sticky(t.tone));

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        role="region"
        aria-label={messages.feedback.notifications}
        className="pointer-events-none fixed inset-x-4 bottom-4 z-[60] flex flex-col items-stretch gap-2 sm:inset-x-auto sm:right-6 sm:bottom-6 sm:w-[440px] sm:max-w-[calc(100vw-3rem)]"
      >
        <div role="status" aria-live="polite" className="flex flex-col gap-2">
          {polite.map((t) => (
            <ToastItem key={t.id} toast={t} onDismiss={dismiss} />
          ))}
        </div>
        <div role="alert" aria-live="assertive" className="flex flex-col gap-2">
          {assertive.map((t) => (
            <ToastItem key={t.id} toast={t} onDismiss={dismiss} />
          ))}
        </div>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const api = useContext(ToastContext);
  if (!api) throw new Error("useToast must be used inside a ToastProvider");
  return api;
}
