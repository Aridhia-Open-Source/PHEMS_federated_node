import { LoadingStar, messages } from "@/ui";

/** Stands in for a page or section while its data loads. */
export function Loading() {
  return <LoadingStar size="page" message={messages.loading} />;
}
