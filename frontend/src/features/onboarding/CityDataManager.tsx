import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { downloadCityPackage, fetchCities, fetchCityCatalog, fetchCityDownload } from "../../api/client";
import { CityPackImport } from "./CityPackImport";
import { errorMessage } from "./setupHelpers";

const DATA_RELEASE_URL = "https://github.com/Uddoo/transit2fog/releases/tag/metro-data-2025-06-r1";
const dataSize = (bytes: number) => bytes < 1024 ** 2 ? `${Math.ceil(bytes / 1024)} KiB` : `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
type Props = { refresh: () => Promise<void>; disabled?: boolean; onBusyChange?: (busy: boolean) => void; headingLevel?: 2 | 3; onStartCity?: (cityId: number) => void };

export function CityDataManager({ refresh, disabled = false, onBusyChange, headingLevel = 3, onStartCity }: Props) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  const client = useQueryClient();
  const headingId = useId();
  const [search, setSearch] = useState("");
  const [cityCode, setCityCode] = useState<string>();
  const lastCompletion = useRef<string | null>(null);
  const observedDownload = useRef(false);
  const [localOpen, setLocalOpen] = useState(false);
  const result = useRef<HTMLDivElement>(null);
  const catalog = useQuery({ queryKey: ["city-catalog"], queryFn: ({ signal }) => fetchCityCatalog(signal), staleTime: Infinity, retry: false });
  const cities = useQuery({ queryKey: ["cities"], queryFn: ({ signal }) => fetchCities({ signal }) });
  const download = useQuery({ queryKey: ["city-download"], queryFn: ({ signal }) => fetchCityDownload(signal), retry: false,
    refetchInterval: (query) => ["downloading", "installing"].includes(query.state.data?.status ?? "") ? 700 : false,
  });
  const start = useMutation({ mutationFn: downloadCityPackage, onSuccess: (state) => client.setQueryData(["city-download"], state) });
  const downloading = ["downloading", "installing"].includes(download.data?.status ?? "");
  useEffect(() => { if (downloading) observedDownload.current = true; }, [downloading]);
  const selection = cityCode ?? download.data?.city_code ?? "";
  const selected = catalog.data?.packages.find((item) => item.city_code === selection);
  const showJobResult = download.data?.city_code === selection;
  const matching = catalog.data?.packages.filter((item) => `${item.city_name} ${item.city_name_en ?? ""} ${item.city_code}`.toLowerCase().includes(search.trim().toLowerCase())) ?? [];
  const installed = selected && cities.data?.find((city) => city.city_code === selected.city_code);
  const current = installed?.checksum === selected?.sha256 && installed !== undefined;
  const completed = download.data?.status === "ready" ? `${download.data.city_code}:${download.data.dataset_id}` : null;
  useEffect(() => {
    if (completed && lastCompletion.current !== completed) {
      lastCompletion.current = completed;
      void refresh();
      if (observedDownload.current) result.current?.focus();
      observedDownload.current = false;
    }
  }, [completed, refresh]);
  useEffect(() => { onBusyChange?.(start.isPending); }, [start.isPending, onBusyChange]);
  return <section className="city-manager" aria-labelledby={headingId}>
    <Heading id={headingId}>选择城市，下载后即可使用</Heading>
    <p className="setup-caption">2025 年 6 月数据快照 · CC BY 4.0 · 按需下载，更新时保留已有行程。</p>
    {catalog.isPending ? <p role="status">正在读取城市目录…</p> : null}
    {catalog.isError ? <div className="city-error" role="alert"><p>城市目录暂不可用，可重试或从数据发布页下载文件。</p><button type="button" className="button button--secondary" onClick={() => void catalog.refetch()}>重新读取目录</button></div> : null}
    {catalog.data ? <>
      <div className="city-picker">
        <label className="field"><span className="field__label">搜索城市</span><input type="search" placeholder="例如：上海、杭州" value={search} disabled={downloading || start.isPending || disabled} onChange={(event) => { setSearch(event.target.value); setCityCode(""); }} /></label>
        <label className="field"><span className="field__label">选择要下载的城市</span><select value={selection} disabled={downloading || start.isPending || disabled} onChange={(event) => { setCityCode(event.target.value); start.reset(); }}><option value="">请选择城市</option>{matching.map((item) => <option key={item.city_code} value={item.city_code}>{item.city_name}{item.city_code === "1886" ? "（上游合并条目）" : ""}</option>)}</select></label>
      </div>
      {matching.length === 0 ? <p role="status">没有找到匹配条目，可以换个名称搜索，或导入本地城市包。</p> : null}
      {selected ? <div className="city-selection"><strong>{selected.city_name} · {catalog.data.data_snapshot}</strong><p>{selected.stations} 个站点 · {selected.ready_variants} 条可用线路方向 · 下载 {dataSize(selected.size)}</p>{selected.city_code === "1886" ? <p className="setup-caption">此条目沿用上游“台湾省”合并分组，并非单座城市。</p> : null}
        <details className="city-source"><summary>数据来源与许可</summary><p>{selected.manifest.source.attribution}</p><p>版本：{selected.manifest.source.version}</p></details>
        {current ? <div className="city-installed-label"><span>此版本已安装</span>{onStartCity ? <button type="button" className="setup-text-action" disabled={disabled} onClick={() => onStartCity(installed.id)}>记录该城市行程 →</button> : <Link to={`/journeys/new?city=${installed.id}`}>记录该城市行程 →</Link>}</div> : <button type="button" className="button button--primary" disabled={downloading || start.isPending || disabled} onClick={() => start.mutate(selected.city_code)}>{downloading || start.isPending ? "正在准备数据…" : `${installed ? "更新" : "下载并安装"}${selected.city_name}`}</button>}
      </div> : null}
    </> : null}
    {downloading && download.data ? <div className="setup-progress" role="status"><strong>{download.data.city_name}：{download.data.message}</strong><progress aria-label="城市数据下载进度" max={download.data.total_bytes || 1} value={download.data.status === "downloading" ? download.data.downloaded_bytes : undefined} /><p>{dataSize(download.data.downloaded_bytes)} / {dataSize(download.data.total_bytes)} · 可以离开后返回查看</p></div> : null}
    <div ref={result} tabIndex={-1} className="city-download-result">
      {download.data?.status === "ready" && showJobResult ? <p role="status">{download.data.message}</p> : null}
      {(download.data?.status === "failed" && showJobResult) || start.isError || download.isError ? <div className="city-error" role="alert"><p>{start.isError ? errorMessage(start.error, "无法开始下载，请重试。") : download.isError ? "暂时无法读取下载状态，请重新连接。" : download.data?.message}</p><button className="button button--secondary" type="button" disabled={start.isPending} onClick={() => download.isError ? void download.refetch() : download.data?.city_code ? start.mutate(download.data.city_code) : selected && start.mutate(selected.city_code)}>{download.isError ? "重新连接" : "重试城市下载"}</button></div> : null}
    </div>
    <p className="setup-caption"><a href={DATA_RELEASE_URL} target="_blank" rel="noreferrer">打开数据发布页 ↗</a> · 网络受限时，也可下载城市包后在下方导入。</p>
    <details className="setup-details city-local" open={localOpen} onToggle={(event) => setLocalOpen(event.currentTarget.open)}><summary>导入本地城市包（离线）</summary><CityPackImport refresh={refresh} disabled={disabled || downloading} onBusyChange={onBusyChange} onInstalled={() => setLocalOpen(false)} /></details>
  </section>;
}

export function InstalledCities() {
  const cities = useQuery({ queryKey: ["cities"], queryFn: ({ signal }) => fetchCities({ signal }) });
  return <section className="installed-cities" aria-label="已安装城市">
    <h2>已安装城市{cities.data ? `（${cities.data.length}）` : ""}</h2>
    {cities.isPending ? <p role="status">正在读取已安装城市…</p> : cities.isError ? <p role="alert">已安装城市读取失败。<button type="button" className="button button--secondary" onClick={() => void cities.refetch()}>重试</button></p> : cities.data?.length === 0 ? <p>还没有城市数据，从上方选择一个城市开始。</p> : <ul>{cities.data?.map((city) => <li key={city.id}><div><strong>{city.name_cn}</strong><p>{city.captured_at ?? "数据时间未提供"} · {city.station_count ?? "—"} 个站点 · {city.direction_count ?? "—"} 条线路方向</p><details><summary>来源与版本</summary><p>{city.source_name} · {city.source_version}</p><p>{city.license}</p></details></div><Link className="button button--secondary" to={`/journeys/new?city=${city.id}`}>记录行程</Link></li>)}</ul>}
  </section>;
}
