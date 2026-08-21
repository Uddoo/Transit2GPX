import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchCityStations,
  fetchCities,
  fetchLines,
  fetchStations,
  fetchRailDataStatus,
  createJourney,
  previewPath,
  previewRailPath,
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

export function useRailDataStatus() {
  return useQuery({
    queryKey: ["rail-data-status"],
    queryFn: ({ signal }) => fetchRailDataStatus(signal),
    staleTime: 30_000,
    refetchInterval: (query) =>
      query.state.data?.status === "importing" ? 1_000 : false,
  });
}

export function useRailPathPreview() {
  return useMutation({ mutationFn: previewRailPath });
}

export function useCreateJourney() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createJourney,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["journeys"] }),
  });
}
