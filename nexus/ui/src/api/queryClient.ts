import { QueryClient } from "@tanstack/react-query";

// No retries or focus refetches: errors toast from the fetch middleware, so a retry
// would toast again and a 401 would loop.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false },
    mutations: { retry: false },
  },
});
