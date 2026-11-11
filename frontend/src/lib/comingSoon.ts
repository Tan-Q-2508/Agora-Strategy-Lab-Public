import { toast } from "sonner";

/** Honest feedback for buttons whose feature is built in a later phase. */
export function comingSoon(what: string): void {
  toast(`${what} arrives in an upcoming update.`, {
    description: "This screen is ready; the feature behind it is being built next.",
  });
}
