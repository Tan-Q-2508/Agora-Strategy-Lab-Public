import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { NavLink } from "react-router";
import { cn } from "../../lib/utils";
import { Tooltip } from "../ui/tooltip";
import { Logo } from "./Logo";
import { NAV, SETTINGS_NAV, type NavItem } from "./nav";

function Item({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const Icon = item.icon;
  const link = (
    <NavLink
      to={item.to}
      end={item.to === "/"}
      aria-label={collapsed ? item.label : undefined}
      className={({ isActive }) =>
        cn(
          "flex h-10 items-center gap-2.5 rounded-control px-2.5 text-[14px] text-fg-muted no-underline transition-colors duration-150",
          "hover:bg-surface-2 hover:text-fg",
          collapsed && "w-11 justify-center px-0",
          isActive && "bg-surface font-semibold text-fg shadow-e1 hover:bg-surface [&_svg]:text-accent-strong",
        )
      }
    >
      <Icon className="size-[18px] shrink-0" aria-hidden="true" />
      {!collapsed && <span>{item.label}</span>}
    </NavLink>
  );
  return collapsed ? (
    <Tooltip content={item.label} side="right">
      {link}
    </Tooltip>
  ) : (
    link
  );
}

export function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <nav
      aria-label="Main"
      className={cn(
        "flex h-full shrink-0 flex-col gap-1 border-r border-border bg-sidebar px-3.5 py-5 transition-[width] duration-200 ease-standard",
        collapsed ? "w-[72px] items-center px-3.5" : "w-[232px]",
      )}
    >
      <div className={cn("flex items-center gap-2.5 px-2.5 pb-4", collapsed && "px-0")}>
        <Logo />
        {!collapsed && <span className="text-[17px] font-bold tracking-tight">Agora</span>}
      </div>
      {NAV.map((item) => (
        <Item key={item.to} item={item} collapsed={collapsed} />
      ))}
      <div className="flex-1" />
      <Item item={SETTINGS_NAV} collapsed={collapsed} />
      <button
        type="button"
        onClick={onToggle}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        className={cn(
          "flex h-10 items-center gap-2.5 rounded-control px-2.5 text-[14px] text-fg-muted hover:bg-surface-2 hover:text-fg",
          collapsed && "w-11 justify-center px-0",
        )}
      >
        {collapsed ? <PanelLeftOpen className="size-[18px]" aria-hidden="true" /> : <PanelLeftClose className="size-[18px]" aria-hidden="true" />}
        {!collapsed && <span>Collapse</span>}
      </button>
    </nav>
  );
}
