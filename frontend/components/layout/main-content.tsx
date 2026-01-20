"use client";

import { ReactNode } from "react";
import { useSidebar } from "./sidebar-context";
import { cn } from "@/lib/utils";

interface MainContentProps {
  children: ReactNode;
}

export function MainContent({ children }: MainContentProps) {
  const { isCollapsed } = useSidebar();

  return (
    <main className={cn(
      "flex-1 min-h-screen section-gradient transition-all duration-300 ease-in-out",
      isCollapsed ? "ml-16" : "ml-72"
    )}>
      <div className={cn(
        "grid-bg fixed inset-0 pointer-events-none opacity-30 transition-all duration-300 ease-in-out",
        isCollapsed ? "ml-16" : "ml-72"
      )} />
      <div className="relative z-10">
        {children}
      </div>
    </main>
  );
}

