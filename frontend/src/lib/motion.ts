/** Motion tokens (DESIGN_BRIEF §5). Framer Motion uses seconds. */
export const duration = { fast: 0.15, base: 0.2, page: 0.45, tick: 0.6 } as const;
export const ease = [0.2, 0.8, 0.2, 1] as const;
export const spring = { type: "spring", stiffness: 400, damping: 30 } as const;

export const pageTransition = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: duration.page, ease } },
  exit: { opacity: 0, y: -4, transition: { duration: duration.fast, ease } },
};
