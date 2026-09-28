export function Pagination({ page, pageSize, total, busy, onChange, label }: {
  page: number;
  pageSize: number;
  total: number;
  busy: boolean;
  onChange: (page: number) => void;
  label: string;
}) {
  return (
    <nav className="table-pagination" aria-label={label}>
      <span>{total ? `第 ${page * pageSize + 1}–${Math.min((page + 1) * pageSize, total)} 条，共 ${total} 条` : "没有符合条件的行程"}</span>
      <div>
        <button className="button button--secondary button--compact" disabled={busy || page === 0} onClick={() => onChange(page - 1)} type="button">上一页</button>
        <button className="button button--secondary button--compact" disabled={busy || (page + 1) * pageSize >= total} onClick={() => onChange(page + 1)} type="button">下一页</button>
      </div>
    </nav>
  );
}
