"use client";

import { Bell, Search, User, Command } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface HeaderProps {
  title: string;
  description?: string;
}

export function Header({ title, description }: HeaderProps) {
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-border bg-background/90 px-8 backdrop-blur-md">
      <div className="flex items-center gap-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
          {description && (
            <p className="text-sm text-muted-foreground">{description}</p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3">
        {/* Search */}
        <div className="relative hidden lg:block">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search assets, campaigns..."
            className="w-72 pl-9 pr-12 h-9 bg-secondary border-border text-sm"
          />
          <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1 text-muted-foreground">
            <kbd className="flex h-5 items-center gap-0.5 rounded border border-border bg-card px-1.5 text-2xs font-mono">
              <Command className="h-2.5 w-2.5" />K
            </kbd>
          </div>
        </div>

        <div className="h-6 w-px bg-border" />

        {/* Notifications */}
        <Button variant="ghost" size="icon" className="relative h-9 w-9">
          <Bell className="h-4 w-4" />
          <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-primary" />
        </Button>

        {/* User */}
        <Button variant="ghost" size="icon" className="h-9 w-9 bg-secondary">
          <User className="h-4 w-4" />
        </Button>
      </div>
    </header>
  );
}
