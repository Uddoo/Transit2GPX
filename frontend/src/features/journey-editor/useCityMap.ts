import { useQuery } from "@tanstack/react-query";

import { fetchCityMap } from "../../api/client";

export function useCityMap({
  cityId,
  lineId,
  enabled,
}: {
  cityId: number;
  lineId?: number;
  enabled: boolean;
}) {
  return useQuery({
    queryKey: ["city-map", cityId, lineId],
    queryFn: ({ signal }) => fetchCityMap({ cityId, lineId, signal }),
    enabled,
    retry: false,
  });
}
