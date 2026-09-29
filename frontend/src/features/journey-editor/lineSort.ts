import type { TransitLine } from "../../api/client";

const lineNameCollator = new Intl.Collator("zh-CN", {
  numeric: true,
  sensitivity: "base",
});

export function sortTransitLines(lines: TransitLine[]) {
  return [...lines].sort(
    (left, right) =>
      lineNameCollator.compare(left.name_cn, right.name_cn) || left.id - right.id,
  );
}

export function groupTransitLines(lines: TransitLine[]) {
  const groups = new Map<string, TransitLine[]>();
  for (const line of lines) {
    let depth = 0;
    let opening = -1;
    for (let index = 0; index < line.name_cn.length; index += 1) {
      const char = line.name_cn[index];
      if (char === "(" || char === "（") { if (depth === 0) opening = index; depth += 1; }
      if (char === ")" || char === "）") depth -= 1;
    }
    const name = opening > 0 && /[)）]$/.test(line.name_cn) && /--|→/.test(line.name_cn.slice(opening)) ? line.name_cn.slice(0, opening) : line.name_cn;
    const group = groups.get(name) ?? [];
    group.push(line); groups.set(name, group);
  }
  return [...groups].map(([name, items]) => ({ name, items }));
}
