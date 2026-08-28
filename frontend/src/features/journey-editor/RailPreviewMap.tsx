import L from "leaflet";
import { useEffect, useMemo } from "react";
import {
  CircleMarker,
  MapContainer,
  Polyline,
  Popup,
  TileLayer,
  ZoomControl,
  useMap,
} from "react-leaflet";

import type { RailPathCandidate, RailStation } from "../../api/client";

const CHINA_CENTER: [number, number] = [35.5, 104.2];
const MUTED_CANDIDATE_COLORS = ["#5e5e5e", "#9c9c9c", "#c8c8c8"] as const;

function candidateColor(candidateId: string, selectedCandidateId: string | undefined, index: number) {
  return candidateId === selectedCandidateId
    ? "#079aa4"
    : MUTED_CANDIDATE_COLORS[index] ?? MUTED_CANDIDATE_COLORS[0];
}

type RailPreviewMapProps = {
  candidates: RailPathCandidate[];
  selectedCandidateId?: string;
  stations: RailStation[];
  onSelectCandidate: (candidateId: string) => void;
  statusMessage?: string;
  tiles?: {
    enabled: boolean;
    url: string;
    attribution: string;
    maxZoom: number;
  };
};

function FitRailSelection({
  candidates,
  stations,
}: Pick<RailPreviewMapProps, "candidates" | "stations">) {
  const map = useMap();

  useEffect(() => {
    const points: [number, number][] = [
      ...candidates.flatMap((candidate) =>
        candidate.geometry.coordinates.map(([lon, lat]) => [lat, lon] as [number, number]),
      ),
      ...stations.map((station) => [station.lat, station.lon] as [number, number]),
    ];
    if (points.length === 0) return;
    const bounds = L.latLngBounds(points);
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [36, 36], maxZoom: 13 });
  }, [candidates, map, stations]);

  return null;
}

export function RailPreviewMap({
  candidates,
  selectedCandidateId,
  stations,
  onSelectCandidate,
  statusMessage,
  tiles,
}: RailPreviewMapProps) {
  const tileSettings = tiles ?? {
    enabled: true,
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  };
  const candidatePositions = useMemo(
    () =>
      candidates.map((candidate) =>
        candidate.geometry.coordinates.map(([lon, lat]) => [lat, lon] as [number, number]),
      ),
    [candidates],
  );

  return (
    <div className="transit-map" role="region" aria-label="铁路候选路径地图">
      <MapContainer
        center={CHINA_CENTER}
        className="transit-map__canvas"
        scrollWheelZoom
        zoom={4}
        zoomControl={false}
      >
        {tileSettings.enabled ? (
          <TileLayer
            attribution={tileSettings.attribution}
            maxZoom={tileSettings.maxZoom}
            url={tileSettings.url}
          />
        ) : null}
        {candidatePositions.map((positions, index) => {
          if (positions.length < 2) return null;
          const candidate = candidates[index];
          const selected = candidate.candidate_id === selectedCandidateId;
          return (
            <Polyline
              eventHandlers={{ click: () => onSelectCandidate(candidate.candidate_id) }}
              key={candidate.candidate_id}
              pathOptions={{
                color: candidateColor(candidate.candidate_id, selectedCandidateId, index),
                lineCap: "round",
                lineJoin: "round",
                opacity: selected ? 1 : 0.68,
                weight: selected ? 8 : 5,
              }}
              positions={positions}
            />
          );
        })}
        {stations.map((station, index) => (
          <CircleMarker
            center={[station.lat, station.lon]}
            key={station.id}
            pathOptions={{
              color: index === 0 || index === stations.length - 1 ? "#079aa4" : "#5e5e5e",
              fillColor: "#ffffff",
              fillOpacity: 1,
              weight: 3,
            }}
            radius={index === 0 || index === stations.length - 1 ? 7 : 5}
          >
            <Popup>{index + 1}. {station.name_cn}</Popup>
          </CircleMarker>
        ))}
        <FitRailSelection candidates={candidates} stations={stations} />
        <ZoomControl position="bottomright" />
      </MapContainer>
      {statusMessage ? (
        <div className="map-status" role="status">
          <strong>{statusMessage}</strong>
          <span>铁路不会回退为公路或直线路径。</span>
        </div>
      ) : null}
      {candidates.length ? (
        <div className="rail-map-legend" aria-label="铁路候选路径图例">
          {candidates.map((candidate, index) => (
            <button
              aria-pressed={candidate.candidate_id === selectedCandidateId}
              key={candidate.candidate_id}
              onClick={() => onSelectCandidate(candidate.candidate_id)}
              type="button"
            >
              <span style={{ backgroundColor: candidateColor(candidate.candidate_id, selectedCandidateId, index) }} />
              候选 {index + 1}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
