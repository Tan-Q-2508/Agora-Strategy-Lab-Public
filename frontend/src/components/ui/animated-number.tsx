import { animate, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { duration, ease } from "../../lib/motion";

/** A number that ticks smoothly to its new value (DESIGN_BRIEF §5). */
export function AnimatedNumber({ value, format }: { value: number; format: (n: number) => string }) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(value);
  const from = useRef(value);

  useEffect(() => {
    if (reduce) {
      from.current = value;
      return;
    }
    const controls = animate(from.current, value, {
      duration: duration.tick,
      ease,
      onUpdate: (v) => setShown(v),
    });
    from.current = value;
    return () => controls.stop();
  }, [value, reduce]);

  return <span>{format(reduce ? value : shown)}</span>;
}
