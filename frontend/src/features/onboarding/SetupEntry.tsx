import { useQuery } from "@tanstack/react-query";
import { Link, Navigate } from "react-router-dom";
import { fetchSetup } from "../../api/client";

export function SetupEntry() {
  const setup = useQuery({ queryKey: ["setup"], queryFn: ({ signal }) => fetchSetup(signal), retry: false });
  if (setup.isPending) return <p className="panel-message" role="status">正在读取本地设置…</p>;
  if (setup.isError) return <div className="panel-message" role="alert"><p>无法连接本地服务。请确认 Transit2Fog 正在运行。</p><button className="button button--secondary" onClick={() => void setup.refetch()} type="button">重新连接</button> <Link to="/setup">打开使用向导</Link></div>;
  return <Navigate replace to={setup.data.should_show ? "/setup" : "/journeys/new"} />;
}
