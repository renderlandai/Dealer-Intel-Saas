"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Bell,
  Search,
  User,
  Command,
  Settings,
  LogOut,
  Megaphone,
  Building2,
  ScanSearch,
  ShieldCheck,
  LayoutDashboard,
  CreditCard,
  AlertTriangle,
  Clock,
  CheckCircle,
  X,
  Image,
  Globe,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { timeAgo } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { useUnreadAlertCount, useRecentAlerts, useMarkAllAlertsRead } from "@/lib/hooks";
import {
  getCampaigns,
  getDistributors,
  getScanJobs,
  getMatches,
  getAlerts,
  type Campaign,
  type Distributor,
  type ScanJob,
  type Match,
  type Alert,
} from "@/lib/api";

interface HeaderProps {
  title: string;
  description?: string;
}

const NAV_ITEMS = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard, keywords: ["home", "overview", "stats"] },
  { name: "Campaigns", href: "/campaigns", icon: Megaphone, keywords: ["assets", "creative", "ads"] },
  { name: "Distributors", href: "/distributors", icon: Building2, keywords: ["dealers", "partners", "network"] },
  { name: "Matches", href: "/matches", icon: Search, keywords: ["results", "found", "detections"] },
  { name: "Scan Jobs", href: "/scans", icon: ScanSearch, keywords: ["scanning", "jobs", "running"] },
  { name: "Compliance", href: "/compliance", icon: ShieldCheck, keywords: ["rules", "violations", "policy"] },
  { name: "Alerts", href: "/alerts", icon: Bell, keywords: ["notifications", "warnings"] },
  { name: "Billing", href: "/settings?tab=billing", icon: CreditCard, keywords: ["plan", "subscription", "payment"] },
  { name: "Settings", href: "/settings", icon: Settings, keywords: ["account", "team", "organization", "profile"] },
];

const STATUS_DOT: Record<string, string> = {
  active: "bg-success",
  completed: "bg-info",
  paused: "bg-amber-400",
  running: "bg-info",
  analyzing: "bg-info",
  pending: "bg-amber-400",
  failed: "bg-destructive",
  inactive: "bg-muted-foreground",
  compliant: "bg-success",
  violation: "bg-destructive",
  review: "bg-amber-400",
};

const SEVERITY_STYLES: Record<string, string> = {
  critical: "text-red-400 bg-red-500/10 border-red-500/20",
  high: "text-red-400 bg-red-500/10 border-red-500/20",
  warning: "text-amber-400 bg-amber-500/10 border-amber-500/20",
  info: "text-info bg-info/10 border-info/20",
};

const ALERT_ICONS: Record<string, typeof AlertTriangle> = {
  compliance_violation: AlertTriangle,
  compliance_drift: AlertTriangle,
  zombie_ad: Clock,
  modified_asset: AlertTriangle,
};

function useClickOutside(ref: React.RefObject<HTMLElement | null>, handler: () => void) {
  useEffect(() => {
    function onMouseDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) handler();
    }
    document.addEventListener("mousedown", onMouseDown);
    return () => document.removeEventListener("mousedown", onMouseDown);
  }, [ref, handler]);
}

/* ─── Search result types ─── */

interface SearchResult {
  id: string;
  category: string;
  label: string;
  sublabel: string;
  href: string;
  icon: typeof Search;
  status?: string;
}

function buildSearchResults(
  campaigns: Campaign[],
  distributors: Distributor[],
  scans: ScanJob[],
  matches: Match[],
  alerts: Alert[],
): SearchResult[] {
  const results: SearchResult[] = [];

  for (const c of campaigns) {
    results.push({
      id: `campaign-${c.id}`,
      category: "Campaigns & Creatives",
      label: c.name,
      sublabel: `${c.asset_count} asset${c.asset_count !== 1 ? "s" : ""} · ${c.status}`,
      href: `/campaigns/${c.id}`,
      icon: Megaphone,
      status: c.status,
    });
  }

  for (const d of distributors) {
    results.push({
      id: `dist-${d.id}`,
      category: "Distributors",
      label: d.name,
      sublabel: [d.region, d.website_url?.replace(/^https?:\/\//, "")].filter(Boolean).join(" · ") || d.status,
      href: `/distributors/${d.id}`,
      icon: Building2,
      status: d.status,
    });
  }

  for (const s of scans) {
    const sourceLabel = s.source.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    results.push({
      id: `scan-${s.id}`,
      category: "Scans",
      label: `${sourceLabel} scan`,
      sublabel: `${s.matches_count} match${s.matches_count !== 1 ? "es" : ""} · ${s.status} · ${timeAgo(s.created_at)}`,
      href: `/scans`,
      icon: ScanSearch,
      status: s.status,
    });
  }

  for (const m of matches) {
    const assetLabel = m.asset_name || "Unknown asset";
    const distLabel = m.distributor_name || "Unknown distributor";
    results.push({
      id: `match-${m.id}`,
      category: "Matches",
      label: `${assetLabel} → ${distLabel}`,
      sublabel: `${m.confidence_score}% · ${m.match_type} · ${m.compliance_status}${m.channel ? ` · ${m.channel}` : ""}`,
      href: `/matches/${m.id}`,
      icon: Image,
      status: m.compliance_status,
    });
  }

  for (const a of alerts) {
    results.push({
      id: `alert-${a.id}`,
      category: "Alerts",
      label: a.title,
      sublabel: `${a.severity} · ${timeAgo(a.created_at)}`,
      href: a.match_id ? `/matches/${a.match_id}` : "/alerts",
      icon: AlertTriangle,
      status: a.severity === "critical" || a.severity === "high" ? "violation" : "pending",
    });
  }

  return results;
}

/* ─── Command Palette ─── */

function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const { data: campaigns = [], isLoading: loadingCampaigns } = useQuery({
    queryKey: ["campaigns"],
    queryFn: getCampaigns,
    enabled: open,
    staleTime: 30_000,
  });
  const { data: distributors = [], isLoading: loadingDistributors } = useQuery({
    queryKey: ["distributors"],
    queryFn: getDistributors,
    enabled: open,
    staleTime: 30_000,
  });
  const { data: scans = [], isLoading: loadingScans } = useQuery({
    queryKey: ["scans"],
    queryFn: getScanJobs,
    enabled: open,
    staleTime: 30_000,
  });
  const { data: matches = [], isLoading: loadingMatches } = useQuery({
    queryKey: ["matches", undefined],
    queryFn: () => getMatches(),
    enabled: open,
    staleTime: 30_000,
  });
  const { data: alerts = [], isLoading: loadingAlerts } = useQuery({
    queryKey: ["alerts", { unreadOnly: false }],
    queryFn: () => getAlerts(),
    enabled: open,
    staleTime: 30_000,
  });

  const isLoading = loadingCampaigns || loadingDistributors || loadingScans || loadingMatches || loadingAlerts;

  const allResults = useMemo(
    () => buildSearchResults(campaigns, distributors, scans, matches, alerts),
    [campaigns, distributors, scans, matches, alerts]
  );

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();

    // Pages always included, filtered by query
    const pages = NAV_ITEMS.filter(
      (item) =>
        !q ||
        item.name.toLowerCase().includes(q) ||
        item.keywords.some((k) => k.includes(q))
    );

    // Data results filtered by query
    const data = q
      ? allResults.filter(
          (r) =>
            r.label.toLowerCase().includes(q) ||
            r.sublabel.toLowerCase().includes(q) ||
            r.category.toLowerCase().includes(q)
        )
      : [];

    return { pages, data };
  }, [query, allResults]);

  const flatItems = useMemo(() => {
    const items: { type: "page" | "result"; index: number }[] = [];
    filtered.pages.forEach((_, i) => items.push({ type: "page", index: i }));
    filtered.data.forEach((_, i) => items.push({ type: "result", index: i }));
    return items;
  }, [filtered]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // Scroll selected item into view
  useEffect(() => {
    if (!listRef.current) return;
    const selected = listRef.current.querySelector("[data-selected='true']");
    if (selected) selected.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  const navigate = useCallback(
    (href: string) => {
      onClose();
      router.push(href);
    },
    [onClose, router]
  );

  useEffect(() => {
    if (!open) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => Math.min(i + 1, flatItems.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const item = flatItems[selectedIndex];
        if (!item) return;
        if (item.type === "page") navigate(filtered.pages[item.index].href);
        else navigate(filtered.data[item.index].href);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose, flatItems, selectedIndex, navigate, filtered]);

  if (!open) return null;

  let flatIdx = -1;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]">
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-xl bg-card border border-border rounded-lg shadow-2xl overflow-hidden">
        {/* Search input */}
        <div className="flex items-center gap-3 border-b border-border px-4">
          <Search className="h-4 w-4 text-muted-foreground shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search campaigns, distributors, scans, matches..."
            className="flex-1 h-12 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none"
          />
          {isLoading && query && (
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground shrink-0" />
          )}
          <kbd className="hidden sm:flex h-5 items-center rounded border border-border bg-secondary px-1.5 text-2xs font-mono text-muted-foreground">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div ref={listRef} className="max-h-96 overflow-y-auto">
          {flatItems.length === 0 && query ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              No results for &ldquo;{query}&rdquo;
            </div>
          ) : (
            <>
              {/* Pages section */}
              {filtered.pages.length > 0 && (
                <div className="p-2">
                  <div className="px-3 py-1.5 text-2xs font-medium uppercase tracking-widest text-muted-foreground">
                    Pages
                  </div>
                  {filtered.pages.map((item) => {
                    flatIdx++;
                    const idx = flatIdx;
                    const Icon = item.icon;
                    return (
                      <button
                        key={item.href}
                        data-selected={idx === selectedIndex}
                        onClick={() => navigate(item.href)}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                          idx === selectedIndex
                            ? "bg-secondary text-foreground"
                            : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                        )}
                      >
                        <Icon className="h-4 w-4 shrink-0" />
                        <span>{item.name}</span>
                      </button>
                    );
                  })}
                </div>
              )}

              {/* Data results grouped by category */}
              {query && filtered.data.length > 0 && (() => {
                const groups: Record<string, typeof filtered.data> = {};
                for (const r of filtered.data) {
                  (groups[r.category] ??= []).push(r);
                }
                return Object.entries(groups).map(([category, items]) => (
                  <div key={category} className="p-2 border-t border-border">
                    <div className="px-3 py-1.5 text-2xs font-medium uppercase tracking-widest text-muted-foreground">
                      {category}
                      <span className="ml-1.5 text-muted-foreground/60">{items.length}</span>
                    </div>
                    {items.map((result) => {
                      flatIdx++;
                      const idx = flatIdx;
                      const Icon = result.icon;
                      const dot = STATUS_DOT[result.status || ""] || "bg-muted-foreground";
                      return (
                        <button
                          key={result.id}
                          data-selected={idx === selectedIndex}
                          onClick={() => navigate(result.href)}
                          className={cn(
                            "flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                            idx === selectedIndex
                              ? "bg-secondary text-foreground"
                              : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
                          )}
                        >
                          <Icon className="h-4 w-4 shrink-0" />
                          <div className="min-w-0 flex-1 text-left">
                            <p className="truncate">{result.label}</p>
                            <p className="truncate text-2xs text-muted-foreground/70">{result.sublabel}</p>
                          </div>
                          {result.status && (
                            <span className={cn("h-2 w-2 shrink-0 rounded-full", dot)} />
                          )}
                        </button>
                      );
                    })}
                  </div>
                ));
              })()}
            </>
          )}
        </div>

        {/* Footer hint */}
        <div className="flex items-center justify-between border-t border-border px-4 py-2 text-2xs text-muted-foreground">
          <span>
            <kbd className="rounded border border-border bg-secondary px-1 py-0.5 font-mono">↑↓</kbd> navigate
            <span className="mx-2">·</span>
            <kbd className="rounded border border-border bg-secondary px-1 py-0.5 font-mono">↵</kbd> open
          </span>
          {!query && <span className="italic">Type to search everything</span>}
        </div>
      </div>
    </div>
  );
}

/* ─── Notification Dropdown ─── */

function NotificationDropdown() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { data: alertData } = useUnreadAlertCount();
  const { data: alerts } = useRecentAlerts(5);
  const markAllRead = useMarkAllAlertsRead();
  const unread = alertData?.unread_count ?? 0;

  useClickOutside(ref, useCallback(() => setOpen(false), []));

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="ghost"
        size="icon"
        className="relative h-9 w-9"
        onClick={() => setOpen((v) => !v)}
        aria-label={`Notifications${unread > 0 ? ` (${unread} unread)` : ""}`}
      >
        <Bell className="h-4 w-4" />
        {unread > 0 && (
          <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[9px] font-mono leading-none text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </Button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 rounded-lg border border-border bg-card shadow-xl z-50">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <span className="text-sm font-semibold">Notifications</span>
            {unread > 0 && (
              <button
                onClick={() => markAllRead.mutate()}
                className="text-xs text-primary hover:text-primary/80 transition-colors"
              >
                Mark all read
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto">
            {!alerts || alerts.length === 0 ? (
              <div className="flex flex-col items-center py-8 text-center">
                <CheckCircle className="h-8 w-8 text-success/50 mb-2" />
                <p className="text-sm text-muted-foreground">All caught up</p>
              </div>
            ) : (
              alerts.map((alert) => {
                const Icon = ALERT_ICONS[alert.alert_type] ?? AlertTriangle;
                const style = SEVERITY_STYLES[alert.severity] ?? "text-muted-foreground bg-secondary border-border";
                return (
                  <Link
                    key={alert.id}
                    href={alert.match_id ? `/matches/${alert.match_id}` : "/alerts"}
                    onClick={() => setOpen(false)}
                    className={cn(
                      "flex items-start gap-3 px-4 py-3 border-b border-border last:border-0 transition-colors hover:bg-secondary/50",
                      !alert.is_read && "bg-primary/[0.03]"
                    )}
                  >
                    <div className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-md border", style)}>
                      <Icon className="h-3.5 w-3.5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className={cn("text-xs leading-snug", !alert.is_read ? "font-medium text-foreground" : "text-muted-foreground")}>
                        {alert.title}
                      </p>
                      <p className="mt-0.5 text-2xs text-muted-foreground">{timeAgo(alert.created_at)}</p>
                    </div>
                    {!alert.is_read && (
                      <div className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary" />
                    )}
                  </Link>
                );
              })
            )}
          </div>

          <div className="border-t border-border">
            <Link
              href="/alerts"
              onClick={() => setOpen(false)}
              className="flex items-center justify-center py-2.5 text-xs font-medium text-primary hover:text-primary/80 transition-colors"
            >
              View all alerts
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── User Menu Dropdown ─── */

function UserMenuDropdown() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { user, signOut } = useAuth();
  const initial = (user?.email?.[0] || "U").toUpperCase();

  useClickOutside(ref, useCallback(() => setOpen(false), []));

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="ghost"
        size="icon"
        className="h-9 w-9 bg-secondary"
        onClick={() => setOpen((v) => !v)}
        aria-label="User menu"
      >
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-[10px] font-semibold text-primary-foreground">
          {initial}
        </div>
      </Button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-56 rounded-lg border border-border bg-card shadow-xl z-50">
          <div className="border-b border-border px-4 py-3">
            <p className="text-sm font-medium truncate">{user?.email || "User"}</p>
            <p className="text-2xs text-muted-foreground mt-0.5">Signed in</p>
          </div>

          <div className="p-1.5">
            <Link
              href="/settings"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
            >
              <Settings className="h-4 w-4" />
              Settings
            </Link>
            <Link
              href="/settings?tab=billing"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
            >
              <CreditCard className="h-4 w-4" />
              Billing
            </Link>
          </div>

          <div className="border-t border-border p-1.5">
            <button
              onClick={() => {
                setOpen(false);
                signOut();
              }}
              className="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
            >
              <LogOut className="h-4 w-4" />
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Header ─── */

export function Header({ title, description }: HeaderProps) {
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <>
      <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-border bg-background/90 px-8 backdrop-blur-md">
        <div className="flex items-center gap-4">
          <div>
            <h1 className="text-lg font-bold tracking-tight">{title}</h1>
            {description && (
              <p className="text-sm text-muted-foreground">{description}</p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Search trigger */}
          <button
            onClick={() => setPaletteOpen(true)}
            className="relative hidden lg:flex items-center w-72 h-9 pl-9 pr-12 rounded-md border border-border bg-secondary text-sm text-muted-foreground hover:bg-secondary/80 transition-colors cursor-pointer"
          >
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2" />
            <span>Search everything...</span>
            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
              <kbd className="flex h-5 items-center gap-0.5 rounded border border-border bg-card px-1.5 text-2xs font-mono">
                <Command className="h-2.5 w-2.5" />K
              </kbd>
            </div>
          </button>

          <div className="h-6 w-px bg-border" />

          <NotificationDropdown />
          <UserMenuDropdown />
        </div>
      </header>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </>
  );
}
