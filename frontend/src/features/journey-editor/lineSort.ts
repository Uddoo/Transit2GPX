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
