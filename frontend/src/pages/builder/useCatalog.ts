import { useEffect, useState } from "react";
import { getJson } from "../../lib/api";
import type { IndicatorInfo } from "../../lib/strategy";

let cache: Record<string, IndicatorInfo> | null = null;
let pending: Promise<Record<string, IndicatorInfo>> | null = null;

function load(): Promise<Record<string, IndicatorInfo>> {
  pending ??= getJson<{ indicators: IndicatorInfo[] }>("/indicators").then((r) => {
    cache = Object.fromEntries(r.indicators.map((i) => [i.key, i]));
    return cache;
  });
  return pending;
}

/** The indicator catalog, fetched once and shared by every builder component. */
export function useCatalog(): Record<string, IndicatorInfo> | null {
  const [cat, setCat] = useState(cache);
  useEffect(() => {
    if (cat) return;
    let alive = true;
    load()
      .then((c) => alive && setCat(c))
      .catch(() => {
        pending = null;
      });
    return () => {
      alive = false;
    };
  }, [cat]);
  return cat;
}
