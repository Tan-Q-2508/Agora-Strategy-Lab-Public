import { SHORTCUT_HELP } from "../../lib/shortcuts";
import { Dialog } from "../ui/dialog";
import { Kbd } from "../ui/kbd";

export function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const isMac = typeof navigator !== "undefined" && /Mac/.test(navigator.platform);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Keyboard shortcuts" description="Single-letter shortcuts work anywhere except while typing.">
      <dl className="m-0 grid grid-cols-[1fr_auto] gap-x-6 gap-y-2.5">
        {SHORTCUT_HELP.map((s) => (
          <div key={s.label} className="contents">
            <dt className="text-[14px] text-fg">{s.label}</dt>
            <dd className="m-0 flex justify-end gap-1">
              {s.keys.map((k, i) => (
                <Kbd key={i}>{k === "Ctrl" && isMac ? "⌘" : k}</Kbd>
              ))}
            </dd>
          </div>
        ))}
      </dl>
    </Dialog>
  );
}
