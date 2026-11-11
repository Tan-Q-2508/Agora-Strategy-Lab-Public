import type { LucideIcon } from "lucide-react";
import { ChartCandlestick, Columns2, Database, FlaskConical, Gauge, Globe2, Home, LayoutGrid, Lightbulb, ListChecks, Newspaper, PieChart, Radio, ScrollText, Settings } from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  keywords?: string;
}

/** The screens in SPEC §9, in sidebar order. */
export const NAV: NavItem[] = [
  { to: "/", label: "Home", icon: Home, keywords: "dashboard start" },
  { to: "/strategies", label: "Strategies", icon: LayoutGrid, keywords: "rules templates builder" },
  { to: "/backtests", label: "Backtests", icon: FlaskConical, keywords: "results test history" },
  { to: "/compare", label: "Compare", icon: Columns2, keywords: "overlay runs" },
  { to: "/paper", label: "Paper trading", icon: Radio, keywords: "live sessions fake money" },
  { to: "/portfolio", label: "Portfolio", icon: PieChart, keywords: "budget allocate allocation opportunities rebalance sleeves diversify lakh" },
  { to: "/metis", label: "Metis", icon: Lightbulb, keywords: "ai researcher ideas research notebook kairos learn" },
  { to: "/charts", label: "Charts", icon: ChartCandlestick, keywords: "price candles indicators" },
  { to: "/watchlists", label: "Watchlists", icon: ListChecks, keywords: "lists sectors large mid small cap index factor momentum theme etf booming rotation" },
  { to: "/indices", label: "Indices", icon: Gauge, keywords: "index indices nifty sensex s&p dow nasdaq sector bank it vix markets today" },
  { to: "/world", label: "World", icon: Globe2, keywords: "geopolitics world events war tariffs oil why did it fall move investigation" },
  { to: "/news", label: "News", icon: Newspaper, keywords: "headlines world geopolitics risk war rates" },
  { to: "/data", label: "Data", icon: Database, keywords: "prices coverage refresh symbols" },
  { to: "/logs", label: "Logs", icon: ScrollText, keywords: "log activity actions history diagnosis what happened" },
];

export const SETTINGS_NAV: NavItem = { to: "/settings", label: "Settings", icon: Settings, keywords: "theme costs ai diagnostics" };
