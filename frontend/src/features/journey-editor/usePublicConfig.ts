import { useQuery } from "@tanstack/react-query";

import { fetchPublicConfig } from "../../api/client";

export function usePublicConfig() {
  return useQuery({
    queryKey: ["public-config"],
    queryFn: ({ signal }) => fetchPublicConfig({ signal }),
    staleTime: Number.POSITIVE_INFINITY,
  });
}
