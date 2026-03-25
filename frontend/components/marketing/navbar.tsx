"use client";

import { useState } from "react";
import Link from "next/link";
import { Zap, Menu, X } from "lucide-react";

const NAV_LINKS = [
  { label: "Features", href: "/landing#features" },
  { label: "How It Works", href: "/landing#how-it-works" },
  { label: "Plans", href: "/pricing" },
];

export function MarketingNav() {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-xl">
      <div className="mx-auto max-w-7xl flex items-center justify-between h-16 px-6">
        <Link href="/landing" className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center bg-primary">
            <Zap className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="text-sm font-semibold tracking-tight uppercase">
            Dealer Intel
          </span>
        </Link>

        <div className="hidden md:flex items-center gap-8">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              {link.label}
            </Link>
          ))}
        </div>

        <div className="hidden md:flex items-center gap-4">
          <Link
            href="/login"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Sign In
          </Link>
          <Link
            href="mailto:sales@dealerintel.com"
            className="h-9 px-5 flex items-center justify-center bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors shadow-glow"
          >
            Book a Demo
          </Link>
        </div>

        <button
          onClick={() => setMobileOpen(!mobileOpen)}
          className="md:hidden p-2 text-muted-foreground hover:text-foreground"
        >
          {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {mobileOpen && (
        <div className="md:hidden border-t border-border bg-background/95 backdrop-blur-xl">
          <div className="px-6 py-4 space-y-4">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setMobileOpen(false)}
                className="block text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                {link.label}
              </Link>
            ))}
            <div className="pt-4 border-t border-border space-y-3">
              <Link
                href="/login"
                className="block text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Sign In
              </Link>
              <Link
                href="mailto:sales@dealerintel.com"
                className="block text-center py-2.5 bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors shadow-glow"
              >
                Book a Demo
              </Link>
            </div>
          </div>
        </div>
      )}
    </nav>
  );
}
