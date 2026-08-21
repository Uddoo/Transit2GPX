import { useQuery } from "@tanstack/react-query";

import { fetchDataStatus } from "../../api/client";

export function useDataStatus() {
  return useQuery({
    queryKey: ["data-status"],
    queryFn: ({ signal }) => fetchDataStatus({ signal }),
    refetchInterval: (query) =>
      query.state.data?.status === "importing" ? 1_500 : false,
  });
}
