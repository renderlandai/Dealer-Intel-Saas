import Link from "next/link";
import { BrandWordmark } from "@/components/ui/brand-wordmark";

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
    <footer className="border-t border-border bg-card/40">
      <div className="mx-auto max-w-7xl px-6 py-16">
        <div className="grid gap-12 md:grid-cols-4">
          <div className="md:col-span-2">
            <Link href="/landing">
              <BrandWordmark className="text-sm" />
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
            <span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />
            <span className="ml-1">All systems operational</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
