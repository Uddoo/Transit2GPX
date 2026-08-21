import {
  useDeferredValue,
  useEffect,
  useId,
  useState,
  type KeyboardEvent,
} from "react";
import { useQuery } from "@tanstack/react-query";

import { searchRailStations, type RailStation } from "../../api/client";

type RailStationComboboxProps = {
  disabled?: boolean;
  label: string;
  name: string;
  onSelect: (station: RailStation) => void;
  searchEnabled?: boolean;
  unavailableMessage?: string;
  value?: RailStation;
};

export function RailStationCombobox({
  disabled,
  label,
  name,
  onSelect,
  searchEnabled = true,
  unavailableMessage,
  value,
}: RailStationComboboxProps) {
  const inputId = useId();
  const listboxId = useId();
  const statusId = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const deferredQuery = useDeferredValue(query.trim());
  const stationSearch = useQuery({
    queryKey: ["rail-station-search", deferredQuery],
    queryFn: ({ signal }) => searchRailStations({ query: deferredQuery, signal }),
    enabled: open && searchEnabled && deferredQuery.length > 0,
    staleTime: 60_000,
  });
  const stations = stationSearch.data ?? [];
  const activeStation = stations[activeIndex];
  const activeOptionId = activeStation
    ? `${listboxId}-option-${activeStation.id}`
    : undefined;

  useEffect(() => setActiveIndex(0), [deferredQuery, stations.length]);

  function close() {
    setOpen(false);
    setQuery("");
    setActiveIndex(0);
  }

  function select(station: RailStation) {
    onSelect(station);
    close();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) => Math.min(current + 1, stations.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((current) => Math.max(current - 1, 0));
    } else if (event.key === "Enter" && open && activeStation) {
      event.preventDefault();
      select(activeStation);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  }

  const status = !searchEnabled
    ? (unavailableMessage ?? "铁路车站数据暂不可用")
    : !deferredQuery
    ? "输入站名、拼音或车站代码"
    : stationSearch.isFetching
      ? "正在搜索铁路车站"
      : stationSearch.isError
        ? "车站搜索失败"
        : stations.length
          ? `${stations.length} 个匹配车站`
          : "没有匹配车站";

  return (
    <div className="field field--station">
      <label className="field__label" htmlFor={inputId}>{label}</label>
      <div className="station-combobox">
        <input
          aria-activedescendant={open ? activeOptionId : undefined}
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-describedby={open ? statusId : undefined}
          aria-expanded={open}
          autoComplete="off"
          disabled={disabled}
          id={inputId}
          name={name}
          onBlur={close}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onClick={() => setOpen(true)}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder="输入铁路站名、拼音或代码"
          role="combobox"
          type="search"
          value={open ? query : (value?.name_cn ?? "")}
        />
        <span aria-hidden="true" className="station-combobox__chevron" />
        {open ? (
          <div className="station-combobox__popup">
            <p className="station-combobox__status" id={statusId} role="status">{status}</p>
            <ul className="station-combobox__list" id={listboxId} role="listbox">
              {stations.map((station, index) => (
                <li
                  aria-selected={station.id === value?.id}
                  className={index === activeIndex ? "is-active" : undefined}
                  id={`${listboxId}-option-${station.id}`}
                  key={station.id}
                  onClick={() => select(station)}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setActiveIndex(index)}
                  role="option"
                >
                  <span>{station.name_cn}</span>
                  <small>
                    {[station.city_name, station.province_name, station.station_code]
                      .filter(Boolean)
                      .join(" · ") || "铁路车站"}
                  </small>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}
