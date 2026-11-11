import { createContext } from "react";
import type { Timeframe } from "../../lib/api";
import type { Issue, ParameterDef } from "../../lib/strategy";

export type Path = (string | number)[];

export interface EditorEnv {
  issues: Issue[];
  params: ParameterDef[];
  timeframe: Timeframe;
  exitRule: boolean; // position checks only make sense in exits
}

export const EnvContext = createContext<EditorEnv>({ issues: [], params: [], timeframe: "1d", exitRule: false });

// Stable keys for conditions so drag-and-drop and open popovers survive edits.
const ids = new WeakMap<object, string>();
let counter = 0;
export function keyOf(c: object): string {
  let id = ids.get(c);
  if (!id) {
    id = `c${++counter}`;
    ids.set(c, id);
  }
  return id;
}
export function carry<T extends object>(from: object, to: T): T {
  const id = ids.get(from);
  if (id) ids.set(to, id);
  return to;
}

