import type { Feature, Geometry, Point } from "geojson";
import L, { type Layer, type PathOptions } from "leaflet";
import { useEffect, useMemo } from "react";
import {
  GeoJSON,
  MapContainer,
  Polyline,
  TileLayer,
  ZoomControl,
  useMap,
} from "react-leaflet";

import type { CityMap, MapFeatureProperties } from "../../api/client";

const DEFAULT_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const DEFAULT_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const SHANGHAI_CENTER: [number, number] = [31.2304, 121.4737];
const CANDIDATE_PATH_COLOR = "#6d28d9";

type MapState = "unavailable" | "loading" | "error" | "empty" | "ready";

type TransitPreviewMapProps = {
  data?: CityMap;
  candidateCoordinates?: [number, number][];
  endStationId?: number;
  startStationId?: number;
  onStationClick?: (stationId: number) => void;
  state: MapState;
  tiles?: {
    enabled: boolean;
    url: string;
    attribution: string;
    maxZoom: number;
  };
};

function FitImportedData({ data }: { data?: CityMap }) {
  const map = useMap();

  useEffect(() => {
    if (!data) {
      return;
    }
    const [minLon, minLat, maxLon, maxLat] = data.bbox;
    const bounds = L.latLngBounds([minLat, minLon], [maxLat, maxLon]);
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [24, 24], maxZoom: 15 });
    }
  }, [data, map]);

  return null;
}

function lineStyle(feature?: Feature<Geometry, MapFeatureProperties>): PathOptions {
  const color = feature?.properties?.display_color;
  return {
    color: typeof color === "string" ? color : "#079aa4",
    opacity: 0.9,
    weight: 5,
  };
}

function stationMarker(
  feature: Feature<Point, unknown>,
  latlng: L.LatLng,
  startStationId?: number,
  endStationId?: number,
) {
  const properties =
    typeof feature.properties === "object" && feature.properties !== null
      ? (feature.properties as Record<string, unknown>)
      : undefined;
  const stationId = properties?.station_id;
  const isEndpoint = stationId === startStationId || stationId === endStationId;
  return L.circleMarker(latlng, {
    radius: isEndpoint ? 7 : 4,
    color: "#007f89",
    fillColor: "#ffffff",
    fillOpacity: 1,
    weight: isEndpoint ? 3 : 2,
  });
}

function bindSafeLabel(
  feature: Feature<Geometry, MapFeatureProperties>,
  layer: Layer,
) {
  const name = feature.properties?.name_cn ?? feature.properties?.name;
  if (typeof name !== "string" || name.length === 0) {
    return;
  }
  const label = document.createElement("span");
  label.textContent = name;
  layer.bindTooltip(label, { direction: "top" });
}

const STATE_COPY: Record<Exclude<MapState, "ready">, { title: string; detail: string }> = {
  unavailable: {
    title: "真实线路数据未就绪",
    detail: "底图可以浏览；导入 CPTOND 后才会显示线路与站点。",
  },
  loading: {
    title: "正在加载真实线路",
    detail: "线路和站点来自本地导入的数据集。",
  },
  error: {
    title: "线路数据加载失败",
    detail: "当前只显示底图，请检查本地数据状态后重试。",
  },
  empty: {
    title: "当前范围没有可用线路",
    detail: "请更换城市或线路；地图不会生成替代几何。",
  },
};

export function TransitPreviewMap({
  candidateCoordinates,
  data,
  endStationId,
  startStationId,
  onStationClick,
  state,
  tiles,
}: TransitPreviewMapProps) {
  const tileSettings = tiles ?? {
    enabled: true,
    url: DEFAULT_TILE_URL,
    attribution: DEFAULT_ATTRIBUTION,
    maxZoom: 19,
  };
  const lines = data?.lines;
  const stations = data?.stations;
  const status = state === "ready" ? undefined : STATE_COPY[state];
  const candidatePositions = useMemo<[number, number][] | undefined>(
    () => candidateCoordinates?.map(([lon, lat]) => [lat, lon]),
    [candidateCoordinates],
  );

  return (
    <div
      className="transit-map"
      role="region"
      aria-label="真实地理底图与已导入地铁线路"
    >
      <MapContainer
        center={SHANGHAI_CENTER}
        className="transit-map__canvas"
        scrollWheelZoom
        zoom={11}
        zoomControl={false}
      >
        {tileSettings.enabled ? (
          <TileLayer
            attribution={tileSettings.attribution}
            maxZoom={tileSettings.maxZoom}
            url={tileSettings.url}
          />
        ) : null}
        {lines && lines.features.length > 0 ? (
          <GeoJSON
            data={lines}
            onEachFeature={bindSafeLabel}
            style={lineStyle}
          />
        ) : null}
        {candidatePositions && candidatePositions.length >= 2 ? (
          <>
            <Polyline
              interactive={false}
              pathOptions={{
                className: "candidate-path candidate-path--halo",
                color: "#ffffff",
                lineCap: "round",
                lineJoin: "round",
                opacity: 0.9,
                weight: 13,
              }}
              positions={candidatePositions}
            />
            <Polyline
              interactive={false}
              pathOptions={{
                className: "candidate-path candidate-path--route",
                color: CANDIDATE_PATH_COLOR,
                lineCap: "round",
                lineJoin: "round",
                opacity: 1,
                weight: 7,
              }}
              positions={candidatePositions}
            />
          </>
        ) : null}
        {stations && stations.features.length > 0 ? (
          <GeoJSON
            data={stations}
            onEachFeature={(feature, layer) => {
              const typedFeature = feature as Feature<Geometry, MapFeatureProperties>;
              bindSafeLabel(typedFeature, layer);
              const stationId = typedFeature.properties?.station_id;
              if (typeof stationId === "number" && onStationClick) {
                layer.on("click", () => onStationClick(stationId));
              }
            }}
            pointToLayer={(feature, latlng) =>
              stationMarker(feature, latlng, startStationId, endStationId)
            }
          />
        ) : null}
        <FitImportedData data={data} />
        <ZoomControl position="bottomright" />
      </MapContainer>

      {status ? (
        <div className="map-status" role="status">
          <strong>{status.title}</strong>
          <span>{status.detail}</span>
        </div>
      ) : null}
      {candidatePositions && candidatePositions.length >= 2 ? (
        <div
          className="map-candidate-legend"
          aria-label="紫色线表示候选路径"
          data-route-color={CANDIDATE_PATH_COLOR}
        >
          <span aria-hidden="true" />
          候选路径
        </div>
      ) : null}
    </div>
  );
}
