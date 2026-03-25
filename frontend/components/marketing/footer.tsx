import Link from "next/link";
import { Zap } from "lucide-react";

const FOOTER_LINKS = {
  Product: [
    { label: "Features", href: "/landing#features" },
    { label: "Pricing", href: "/pricing" },
    { label: "How It Works", href: "/landing#how-it-works" },
  ],
  Company: [
    { label: "Sign In", href: "/login" },
    { label: "Start Free Trial", href: "/login" },
  ],
};

export function MarketingFooter() {
  return (
    <footer className="border-t border-border bg-card/30">
      <div className="mx-auto max-w-7xl px-6 py-16">
        <div className="grid gap-12 md:grid-cols-4">
          <div className="md:col-span-2">
            <Link href="/landing" className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center bg-primary">
                <Zap className="h-4 w-4 text-primary-foreground" />
              </div>
              <span className="text-sm font-semibold tracking-tight uppercase">
                Dealer Intel
              </span>
            </Link>
            <p className="mt-4 text-sm text-muted-foreground max-w-xs leading-relaxed">
              AI-powered campaign asset monitoring for distributor networks.
              Protect your brand across every channel.
            </p>
          </div>

          {Object.entries(FOOTER_LINKS).map(([heading, links]) => (
            <div key={heading}>
              <h4 className="text-2xs font-semibold uppercase tracking-wider text-muted-foreground mb-4">
                {heading}
              </h4>
              <ul className="space-y-3">
                {links.map((link) => (
                  <li key={link.label}>
                    <Link
                      href={link.href}
                      className="text-sm text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-16 pt-8 border-t border-border flex flex-col sm:flex-row items-center justify-between gap-4">
          <p className="text-xs text-muted-foreground">
            &copy; {new Date().getFullYear()} Dealer Intel. All rights reserved.
          </p>
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <span className="status-dot active" />
            <span className="ml-1">All systems operational</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
