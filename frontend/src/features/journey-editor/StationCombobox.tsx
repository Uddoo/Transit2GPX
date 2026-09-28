import {
  useDeferredValue,
  useEffect,
  useId,
  useMemo,
  useState,
  type KeyboardEvent,
} from "react";

import type { Station } from "../../api/client";
import { useStationSearch } from "./useJourneyNetwork";

const MAX_VISIBLE_RESULTS = 50;

type StationComboboxProps = {
  clearable?: boolean;
  cityId?: number;
  disabled: boolean;
  emptyLabel?: string;
  label: string;
  lineId?: number;
  name: string;
  onClear?: () => void;
  onFocus?: () => void;
  onSelect: (stationId: number) => void;
  placeholder: string;
  stations: Station[];
  value?: number;
};

function stationMatches(station: Station, query: string) {
  const normalizedQuery = query.toLocaleLowerCase();
  return (
    station.name_cn.toLocaleLowerCase().includes(normalizedQuery) ||
    station.name_en?.toLocaleLowerCase().includes(normalizedQuery)
  );
}

export function StationCombobox({
  clearable = false,
  cityId,
  disabled,
  emptyLabel = "不指定",
  label,
  lineId,
  name,
  onClear,
  onFocus,
  onSelect,
  placeholder,
  stations,
  value,
}: StationComboboxProps) {
  const inputId = useId();
  const listboxId = useId();
  const statusId = useId();
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);
  const normalizedQuery = query.trim();
  const deferredQuery = useDeferredValue(normalizedQuery);
  const selectedStation = useMemo(
    () => stations.find((station) => station.id === value),
    [stations, value],
  );
  const stationSearch = useStationSearch({
    query: deferredQuery,
    cityId,
    lineId,
    enabled: isOpen,
  });
  const matches = useMemo(() => {
    if (!normalizedQuery) {
      return stations;
    }
    const localMatches = stations.filter((station) =>
      stationMatches(station, normalizedQuery),
    );
    const merged = new Map<number, Station>();
    for (const station of localMatches) merged.set(station.id, station);
    if (deferredQuery === normalizedQuery) {
      for (const station of stationSearch.data ?? []) merged.set(station.id, station);
    }
    return [...merged.values()];
  }, [deferredQuery, normalizedQuery, stationSearch.data, stations]);
  const visibleMatches = matches.slice(0, MAX_VISIBLE_RESULTS);
  const showClearOption = clearable && !normalizedQuery;
  const stationIndex = activeIndex - (showClearOption ? 1 : 0);
  const activeStation = visibleMatches[stationIndex];
  const activeOptionId =
    showClearOption && activeIndex === 0
      ? `${listboxId}-option-clear`
      : activeStation
        ? `${listboxId}-option-${activeStation.id}`
        : undefined;
  const inputValue = isOpen
    ? query
    : (selectedStation?.name_cn ?? (clearable ? emptyLabel : ""));
  const optionCount = visibleMatches.length + (showClearOption ? 1 : 0);

  useEffect(() => {
    setActiveIndex(optionCount > 0 ? 0 : -1);
  }, [normalizedQuery, optionCount]);

  function open() {
    setQuery("");
    setIsOpen(true);
    onFocus?.();
  }

  function close() {
    setIsOpen(false);
    setQuery("");
    setActiveIndex(-1);
  }

  function select(station: Station) {
    onSelect(station.id);
    close();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!isOpen) open();
      setActiveIndex((current) =>
        Math.min(current + 1, optionCount - 1),
      );
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!isOpen) open();
      setActiveIndex((current) => Math.max(current - 1, 0));
      return;
    }
    if (
      event.key === "Enter" &&
      isOpen &&
      showClearOption &&
      activeIndex === 0
    ) {
      event.preventDefault();
      onClear?.();
      close();
      return;
    }
    if (event.key === "Enter" && isOpen && activeStation) {
      event.preventDefault();
      select(activeStation);
      return;
    }
    if (event.key === "Escape" && isOpen) {
      event.preventDefault();
      close();
    }
  }

  const resultStatus = stationSearch.isFetching
    ? "正在搜索站点"
    : matches.length === 0
      ? "没有匹配站点"
      : matches.length > MAX_VISIBLE_RESULTS
        ? `显示前 ${MAX_VISIBLE_RESULTS} 个站点，共 ${matches.length} 个`
        : `${matches.length} 个匹配站点`;

  return (
    <div className="field field--station">
      <label className="field__label" htmlFor={inputId}>
        {label}
      </label>
      <div className="station-combobox">
        <input
          aria-activedescendant={
            isOpen ? activeOptionId : undefined
          }
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-describedby={isOpen ? statusId : undefined}
          aria-expanded={isOpen}
          autoComplete="off"
          disabled={disabled}
          id={inputId}
          name={name}
          onBlur={close}
          onChange={(event) => {
            setQuery(event.target.value);
            setIsOpen(true);
          }}
          onClick={() => {
            if (!isOpen) open();
          }}
          onFocus={() => {
            if (!isOpen) open();
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          role="combobox"
          type="search"
          value={inputValue}
        />
        <span aria-hidden="true" className="station-combobox__chevron" />
        {isOpen ? (
          <div className="station-combobox__popup">
            <p className="station-combobox__status" id={statusId} role="status">
              {resultStatus}
            </p>
            <ul className="station-combobox__list" id={listboxId} role="listbox">
              {showClearOption ? (
                <li
                  aria-selected={value === undefined}
                  className={activeIndex === 0 ? "is-active" : undefined}
                  id={`${listboxId}-option-clear`}
                  onClick={() => {
                    onClear?.();
                    close();
                  }}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setActiveIndex(0)}
                  role="option"
                >
                  <span>{emptyLabel}</span>
                  <small>清除已选途经站</small>
                </li>
              ) : null}
              {visibleMatches.map((station, index) => (
                <li
                  aria-selected={station.id === value}
                  className={
                    index + (showClearOption ? 1 : 0) === activeIndex
                      ? "is-active"
                      : undefined
                  }
                  id={`${listboxId}-option-${station.id}`}
                  key={station.id}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() =>
                    setActiveIndex(index + (showClearOption ? 1 : 0))
                  }
                  onClick={() => select(station)}
                  role="option"
                >
                  <span>{station.name_cn}</span>
                  {station.name_en ? <small>{station.name_en}</small> : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}
