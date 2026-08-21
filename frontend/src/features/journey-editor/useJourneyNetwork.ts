import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchCityStations,
  fetchCities,
  fetchLines,
  fetchStations,
  createJourney,
  previewPath,
  searchStations,
} from "../../api/client";

export function useCities(enabled: boolean) {
  return useQuery({
    queryKey: ["cities"],
    queryFn: ({ signal }) => fetchCities({ signal }),
    enabled,
  });
}

export function useLines(cityId?: number) {
  return useQuery({
    queryKey: ["lines", cityId],
    queryFn: ({ signal }) => fetchLines(cityId as number, signal),
    enabled: cityId !== undefined,
  });
}

export function useStations(cityId?: number, lineId?: number, includeAll = false) {
  return useQuery({
    queryKey: ["stations", cityId, lineId, includeAll],
    queryFn: ({ signal }) =>
      includeAll
        ? fetchCityStations(cityId as number, signal)
        : fetchStations(lineId as number, signal),
    enabled: cityId !== undefined && (includeAll || lineId !== undefined),
  });
}

export function useStationSearch({
  query,
  cityId,
  lineId,
  enabled,
}: {
  query: string;
  cityId?: number;
  lineId?: number;
  enabled: boolean;
}) {
  return useQuery({
    queryKey: ["station-search", cityId, lineId, query],
    queryFn: ({ signal }) =>
      searchStations({
        query,
        cityId: cityId as number,
        lineId,
        signal,
      }),
    enabled: enabled && cityId !== undefined && query.length > 0,
    staleTime: 60_000,
  });
}

export function usePathPreview() {
  return useMutation({ mutationFn: previewPath });
}

export function useCreateJourney() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createJourney,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["journeys"] }),
  });
}
