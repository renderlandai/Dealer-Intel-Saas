"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Megaphone,
  Building2,
  Search,
  ScanSearch,
  Settings,
  Bell,
  Zap,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useSidebar } from "./sidebar-context";

const navigation = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Campaigns", href: "/campaigns", icon: Megaphone },
  { name: "Distributors", href: "/distributors", icon: Building2 },
  { name: "Matches", href: "/matches", icon: Search },
  { name: "Scan Jobs", href: "/scans", icon: ScanSearch },
];

const secondaryNav = [
  { name: "Alerts", href: "/alerts", icon: Bell },
  { name: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const { isCollapsed, toggleSidebar } = useSidebar();

  return (
    <aside 
      className={cn(
        "fixed left-0 top-0 z-40 h-screen bg-card border-r border-border transition-all duration-300 ease-in-out",
        isCollapsed ? "w-16" : "w-72"
      )}
    >
      <div className="flex h-full flex-col">
        {/* Logo */}
        <div className={cn(
          "flex h-18 items-center border-b border-border transition-all duration-300",
          isCollapsed ? "justify-center px-2" : "gap-3 px-6"
        )}>
          <div className="flex h-10 w-10 items-center justify-center bg-primary flex-shrink-0">
            <Zap className="h-5 w-5 text-primary-foreground" />
          </div>
          {!isCollapsed && (
            <div className="overflow-hidden">
              <h1 className="text-base font-semibold tracking-tight whitespace-nowrap">DEALER INTEL</h1>
              <p className="text-2xs uppercase tracking-widest text-muted-foreground whitespace-nowrap">
                Asset Intelligence
              </p>
            </div>
          )}
        </div>

        {/* Main Navigation */}
        <nav className="flex-1 p-4 overflow-hidden">
          {!isCollapsed && (
            <div className="mb-4">
              <span className="px-3 text-2xs font-medium uppercase tracking-widest text-muted-foreground">
                Navigation
              </span>
            </div>
          )}
          
          <div className="space-y-1">
            {navigation.map((item, index) => {
              const isActive = pathname === item.href || 
                (item.href !== "/" && pathname.startsWith(item.href));
              
              return (
                <Link
                  key={item.name}
                  href={item.href}
                  title={isCollapsed ? item.name : undefined}
                  className={cn(
                    "group flex items-center gap-3 py-2.5 text-sm font-medium transition-all",
                    "opacity-0 animate-fade-up",
                    isCollapsed ? "justify-center px-2" : "px-3",
                    isActive
                      ? "bg-secondary text-foreground border-l-2 border-primary -ml-px"
                      : "text-muted-foreground hover:text-foreground hover:bg-secondary/50"
                  )}
                  style={{ animationDelay: `${index * 50}ms`, animationFillMode: 'forwards' }}
                >
                  <item.icon className={cn(
                    "h-4 w-4 transition-colors flex-shrink-0",
                    isActive ? "text-primary" : "text-muted-foreground group-hover:text-foreground"
                  )} />
                  {!isCollapsed && (
                    <>
                      <span className="truncate">{item.name}</span>
                      {isActive && (
                        <div className="ml-auto w-1.5 h-1.5 bg-primary rounded-full flex-shrink-0" />
                      )}
                    </>
                  )}
                </Link>
              );
            })}
          </div>

          {!isCollapsed && (
            <div className="mt-8 mb-4">
              <span className="px-3 text-2xs font-medium uppercase tracking-widest text-muted-foreground">
                System
              </span>
            </div>
          )}
          
          {isCollapsed && <div className="my-4 border-t border-border" />}
          
          <div className="space-y-1">
            {secondaryNav.map((item, index) => {
              const isActive = pathname === item.href;
              
              return (
                <Link
                  key={item.name}
                  href={item.href}
                  title={isCollapsed ? item.name : undefined}
                  className={cn(
                    "group flex items-center gap-3 py-2.5 text-sm font-medium transition-all",
                    "opacity-0 animate-fade-up",
                    isCollapsed ? "justify-center px-2 relative" : "px-3",
                    isActive
                      ? "bg-secondary text-foreground border-l-2 border-primary -ml-px"
                      : "text-muted-foreground hover:text-foreground hover:bg-secondary/50"
                  )}
                  style={{ animationDelay: `${(navigation.length + index) * 50}ms`, animationFillMode: 'forwards' }}
                >
                  <div className="relative flex-shrink-0">
                    <item.icon className="h-4 w-4" />
                    {item.name === "Alerts" && isCollapsed && (
                      <span className="absolute -top-1.5 -right-1.5 flex h-4 w-4 items-center justify-center bg-destructive text-[9px] font-mono text-white rounded-full">
                        3
                      </span>
                    )}
                  </div>
                  {!isCollapsed && (
                    <>
                      <span className="truncate">{item.name}</span>
                      {item.name === "Alerts" && (
                        <span className="ml-auto flex h-5 w-5 items-center justify-center bg-destructive text-2xs font-mono text-white flex-shrink-0">
                          3
                        </span>
                      )}
                    </>
                  )}
                </Link>
              );
            })}
          </div>
        </nav>

        {/* Footer */}
        <div className="border-t border-border p-4">
          {!isCollapsed ? (
            <div className="p-4 bg-secondary/50 border border-border">
              <div className="flex items-center gap-2 mb-2">
                <div className="status-dot active" />
                <span className="text-xs font-medium">System Online</span>
              </div>
              <p className="text-2xs text-muted-foreground leading-relaxed">
                Last scan completed 12m ago. All systems operational.
              </p>
            </div>
          ) : (
            <div className="flex justify-center">
              <div className="status-dot active" title="System Online" />
            </div>
          )}
        </div>

        {/* Collapse Toggle Button */}
        <button
          onClick={toggleSidebar}
          className="absolute -right-3 top-20 flex h-6 w-6 items-center justify-center rounded-full bg-card border border-border hover:bg-secondary transition-colors"
          aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {isCollapsed ? (
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
          ) : (
            <ChevronLeft className="h-3.5 w-3.5 text-muted-foreground" />
          )}
        </button>
      </div>
    </aside>
  );
}
