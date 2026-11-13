import { useEffect } from "react";

import { useToast } from "@/ui";

let toast: ReturnType<typeof useToast> | null = null;

/** For code outside React (the API client). Needs <ToastBridge /> mounted under the ToastProvider. */
export function showToast(text: string, kind: "error" | "info" = "error") {
  toast!.show({ tone: kind, message: text });
}

export function ToastBridge() {
  const api = useToast();
  useEffect(() => {
    toast = api;
    return () => {
      toast = null;
    };
  }, [api]);
  return null;
}
