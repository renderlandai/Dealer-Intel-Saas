"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Check,
  ArrowRight,
  ChevronDown,
  Minus,
} from "lucide-react";
import { MarketingNav } from "@/components/marketing/navbar";
import { MarketingFooter } from "@/components/marketing/footer";

/* ────────────────────────────────────────────────────────── */
/*  Data                                                      */
/* ────────────────────────────────────────────────────────── */

const TIERS = [
  {
    id: "free",
    name: "Free Trial",
    tag: "14 days · No credit card",
    description: "Explore the platform with a small test network.",
    cta: "Start Free Trial",
    ctaHref: "/login",
    ctaStyle: "border border-border hover:bg-secondary" as const,
    highlights: [
      "2 dealers",
      "1 campaign",
      "5 total scans",
      "Website channel only",
      "21-day data retention",
    ],
  },
  {
    id: "starter",
    name: "Starter",
    tag: "Up to 10 dealers",
    description: "For small dealer networks getting started with compliance monitoring.",
    cta: "Book a Demo",
    ctaHref: "mailto:sales@dealerintel.com",
    ctaStyle: "border border-border hover:bg-secondary" as const,
    highlights: [
      "10 dealers included",
      "3 campaigns",
      "15 scans / month",
      "Website scanning",
      "Biweekly & monthly scheduling",
      "CSV exports",
    ],
  },
  {
    id: "professional",
    name: "Professional",
    tag: "Up to 40 dealers",
    popular: true,
    description: "For growing brands that need full multi-channel visibility.",
    cta: "Book a Demo",
    ctaHref: "mailto:sales@dealerintel.com",
    ctaStyle: "bg-primary text-primary-foreground hover:bg-primary/90 shadow-glow" as const,
    highlights: [
      "40 dealers included",
      "10 campaigns",
      "40 scans / month",
      "All 4 channels",
      "PDF reports + branding",
      "Email alerts",
      "Adaptive AI calibration",
    ],
  },
  {
    id: "business",
    name: "Business",
    tag: "Up to 100 dealers",
    description: "For established networks with high-volume monitoring needs.",
    cta: "Book a Demo",
    ctaHref: "mailto:sales@dealerintel.com",
    ctaStyle: "border border-border hover:bg-secondary" as const,
    highlights: [
      "100 dealers included",
      "Unlimited campaigns",
      "150 scans / month",
      "All 4 channels",
      "Daily scheduling",
      "Compliance trend analytics",
      "10 user seats",
    ],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    tag: "Unlimited · Custom SLA",
    description: "Tailored for large-scale manufacturer networks with custom needs.",
    cta: "Contact Sales",
    ctaHref: "mailto:sales@dealerintel.com",
    ctaStyle: "border border-border hover:bg-secondary" as const,
    highlights: [
      "Unlimited dealers",
      "Unlimited campaigns & scans",
      "All channels + API access",
      "Slack notifications",
      "White-label reports",
      "2-year data retention",
      "Unlimited user seats",
      "Dedicated support",
    ],
  },
];

/* Each row: [label, free, starter, pro, business, enterprise] */
type CellValue = boolean | string;

interface ComparisonRow {
  label: string;
  values: [CellValue, CellValue, CellValue, CellValue, CellValue];
}

interface ComparisonGroup {
  heading: string;
  rows: ComparisonRow[];
}

const COMPARISON: ComparisonGroup[] = [
  {
    heading: "Core Limits",
    rows: [
      { label: "Dealers included", values: ["2", "10", "40", "100", "Unlimited"] },
      { label: "Campaigns", values: ["1", "3", "10", "Unlimited", "Unlimited"] },
      { label: "Scans", values: ["5 total", "15 / mo", "40 / mo", "150 / mo", "Unlimited"] },
      { label: "Concurrent scans", values: ["1", "1", "2", "5", "10"] },
      { label: "Pages per site", values: ["8", "8", "15", "20", "50"] },
      { label: "User seats", values: ["1", "1", "3", "10", "Unlimited"] },
    ],
  },
  {
    heading: "Channels",
    rows: [
      { label: "Website scanning", values: [true, true, true, true, true] },
      { label: "Google Ads scanning", values: [false, false, true, true, true] },
      { label: "Facebook scanning", values: [false, false, true, true, true] },
      { label: "Instagram scanning", values: [false, false, true, true, true] },
    ],
  },
  {
    heading: "Scheduling",
    rows: [
      { label: "Monthly scheduling", values: [false, true, true, true, true] },
      { label: "Biweekly scheduling", values: [false, true, true, true, true] },
      { label: "Weekly scheduling", values: [false, false, true, true, true] },
      { label: "Daily scheduling", values: [false, false, false, true, true] },
    ],
  },
  {
    heading: "Reporting & Analytics",
    rows: [
      { label: "CSV exports", values: [true, true, true, true, true] },
      { label: "PDF reports", values: ["1 report", false, true, true, true] },
      { label: "Report branding", values: [false, false, true, true, true] },
      { label: "Compliance trend analytics", values: [false, false, false, true, true] },
    ],
  },
  {
    heading: "Alerts & Integrations",
    rows: [
      { label: "Email notifications", values: [false, false, true, true, true] },
      { label: "Slack notifications", values: [false, false, false, false, true] },
      { label: "API access", values: [false, false, false, false, true] },
    ],
  },
  {
    heading: "AI & Data",
    rows: [
      { label: "Adaptive AI calibration", values: [false, false, true, true, true] },
      { label: "Data retention", values: ["21 days", "90 days", "6 months", "1 year", "2 years"] },
      { label: "Extra dealers available", values: [false, true, true, true, true] },
    ],
  },
];

const FAQ = [
  {
    q: "How does the 14-day free trial work?",
    a: "Sign up, add up to 2 dealers and 1 campaign, and run up to 5 website scans. No credit card required. Your data is preserved if you upgrade before the trial ends.",
  },
  {
    q: "What happens if I need more dealers than my plan includes?",
    a: "Every paid plan supports extra dealers at a per-dealer monthly rate that varies by tier. Your account manager will walk you through the options during your demo.",
  },
  {
    q: "Can I change plans at any time?",
    a: "Yes. Upgrade or downgrade from the billing page inside the app. Upgrades take effect immediately; downgrades apply at the end of your current billing cycle.",
  },
  {
    q: "What counts as a \"scan\"?",
    a: "A scan is one channel sweep across your dealer network — for example, scanning all 10 dealers' websites counts as 1 scan. Each channel (website, Google Ads, Facebook, Instagram) counts separately.",
  },
  {
    q: "How does pricing work?",
    a: "Pricing is based on the size of your dealer network, the channels you need, and your scan volume. Book a demo and we'll build a plan tailored to your needs.",
  },
  {
    q: "What kind of support is included?",
    a: "All plans include email support. Business and Enterprise plans include priority response times. Enterprise includes a dedicated account manager.",
  },
];

/* ────────────────────────────────────────────────────────── */
/*  Components                                                */
/* ────────────────────────────────────────────────────────── */

function CellDisplay({ value }: { value: CellValue }) {
  if (value === true) return <Check className="h-4 w-4 text-primary mx-auto" />;
  if (value === false) return <Minus className="h-4 w-4 text-muted-foreground/40 mx-auto" />;
  return <span className="text-sm font-mono">{value}</span>;
}

function FaqItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border-b border-border">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between py-5 text-left"
      >
        <span className="text-sm font-medium pr-4">{q}</span>
        <ChevronDown
          className={`h-4 w-4 text-muted-foreground flex-shrink-0 transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>
      {open && (
        <p className="pb-5 text-sm text-muted-foreground leading-relaxed pr-8">
          {a}
        </p>
      )}
    </div>
  );
}

/* ────────────────────────────────────────────────────────── */
/*  Page                                                      */
/* ────────────────────────────────────────────────────────── */

export default function PricingPage() {
  return (
    <div className="min-h-screen bg-background">
      <MarketingNav />

      {/* ─── Header ─── */}
      <section className="pt-32 pb-20 relative overflow-hidden">
        <div className="absolute inset-0 grid-bg opacity-20" />
        <div className="relative mx-auto max-w-3xl px-6 text-center">
          <p className="text-2xs font-semibold uppercase tracking-wider text-primary mb-3 opacity-0 animate-fade-up">
            Pricing
          </p>
          <h1 className="text-4xl md:text-5xl font-semibold tracking-[-0.02em] opacity-0 animate-fade-up delay-75">
            Plans that scale with
            <br />
            <span className="text-primary">your dealer network</span>
          </h1>
          <p className="mt-4 text-muted-foreground max-w-lg mx-auto leading-relaxed opacity-0 animate-fade-up delay-150">
            Custom pricing based on your network size. Start with a free
            trial, then book a demo to find the right plan.
          </p>
        </div>
      </section>

      {/* ─── Tier Cards ─── */}
      <section className="pb-28">
        <div className="mx-auto max-w-7xl px-6">
          {/* Top 3 tiers — main focus */}
          <div className="grid gap-6 lg:grid-cols-3 max-w-5xl mx-auto mb-8">
            {TIERS.filter((t) =>
              ["starter", "professional", "business"].includes(t.id)
            ).map((tier, i) => (
              <div
                key={tier.id}
                className={`relative p-8 border bg-card opacity-0 animate-fade-up ${
                  tier.popular
                    ? "border-primary/50 shadow-glow lg:-mt-4 lg:pb-12"
                    : "border-border"
                }`}
                style={{
                  animationDelay: `${100 + i * 100}ms`,
                  animationFillMode: "forwards",
                }}
              >
                {tier.popular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 bg-primary text-primary-foreground text-2xs font-semibold uppercase tracking-wider">
                    Most Popular
                  </div>
                )}

                <h3 className="text-lg font-semibold">{tier.name}</h3>
                <p className="mt-2 text-sm font-mono text-primary">
                  {tier.tag}
                </p>
                <p className="mt-3 text-sm text-muted-foreground leading-relaxed min-h-[40px]">
                  {tier.description}
                </p>

                <Link
                  href={tier.ctaHref}
                  className={`mt-6 h-10 w-full flex items-center justify-center text-sm font-medium transition-all ${tier.ctaStyle}`}
                >
                  {tier.cta}
                </Link>

                <ul className="mt-6 pt-6 border-t border-border space-y-3">
                  {tier.highlights.map((h) => (
                    <li key={h} className="flex items-start gap-2 text-sm">
                      <Check className="h-3.5 w-3.5 text-primary flex-shrink-0 mt-0.5" />
                      <span className="text-foreground/80">{h}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          {/* Free Trial + Enterprise — smaller cards below */}
          <div className="grid gap-6 md:grid-cols-2 max-w-5xl mx-auto">
            {TIERS.filter((t) =>
              ["free", "enterprise"].includes(t.id)
            ).map((tier, i) => (
              <div
                key={tier.id}
                className="p-8 border border-border bg-card opacity-0 animate-fade-up"
                style={{
                  animationDelay: `${400 + i * 100}ms`,
                  animationFillMode: "forwards",
                }}
              >
                <div className="flex items-baseline justify-between">
                  <div>
                    <h3 className="text-lg font-semibold">{tier.name}</h3>
                    <p className="mt-1 text-sm font-mono text-primary">
                      {tier.tag}
                    </p>
                  </div>
                  <Link
                    href={tier.ctaHref}
                    className={`h-9 px-5 flex items-center justify-center text-sm font-medium transition-all flex-shrink-0 ${tier.ctaStyle}`}
                  >
                    {tier.cta}
                  </Link>
                </div>
                <p className="mt-3 text-sm text-muted-foreground leading-relaxed">
                  {tier.description}
                </p>
                <ul className="mt-4 grid grid-cols-2 gap-2">
                  {tier.highlights.map((h) => (
                    <li key={h} className="flex items-start gap-2 text-sm">
                      <Check className="h-3.5 w-3.5 text-primary flex-shrink-0 mt-0.5" />
                      <span className="text-foreground/80">{h}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── Feature Comparison Table ─── */}
      <section className="py-28 border-y border-border section-gradient">
        <div className="mx-auto max-w-7xl px-6">
          <div className="text-center mb-16">
            <h2 className="text-3xl font-semibold tracking-[-0.02em]">
              Compare every feature
            </h2>
            <p className="mt-3 text-muted-foreground">
              See exactly what&apos;s included in each plan.
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[800px]">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-4 pr-4 text-sm font-semibold w-[240px]">
                    Feature
                  </th>
                  {["Free Trial", "Starter", "Professional", "Business", "Enterprise"].map(
                    (name) => (
                      <th
                        key={name}
                        className={`text-center py-4 px-3 text-sm font-semibold ${
                          name === "Professional" ? "text-primary" : ""
                        }`}
                      >
                        {name}
                      </th>
                    )
                  )}
                </tr>
              </thead>
              {COMPARISON.map((group) => (
                <tbody key={group.heading}>
                  <tr>
                    <td
                      colSpan={6}
                      className="pt-8 pb-3 text-2xs font-semibold uppercase tracking-wider text-primary"
                    >
                      {group.heading}
                    </td>
                  </tr>
                  {group.rows.map((row) => (
                    <tr
                      key={row.label}
                      className="border-b border-border/50 hover:bg-card/50 transition-colors"
                    >
                      <td className="py-3.5 pr-4 text-sm text-muted-foreground">
                        {row.label}
                      </td>
                      {row.values.map((val, j) => (
                        <td key={j} className="py-3.5 px-3 text-center">
                          <CellDisplay value={val} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              ))}
            </table>
          </div>
        </div>
      </section>

      {/* ─── FAQ ─── */}
      <section className="py-28">
        <div className="mx-auto max-w-3xl px-6">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-semibold tracking-[-0.02em]">
              Frequently asked questions
            </h2>
          </div>

          <div className="border-t border-border">
            {FAQ.map((item) => (
              <FaqItem key={item.q} q={item.q} a={item.a} />
            ))}
          </div>
        </div>
      </section>

      {/* ─── Bottom CTA ─── */}
      <section className="py-20 border-t border-border section-gradient">
        <div className="mx-auto max-w-3xl px-6 text-center">
          <h2 className="text-2xl md:text-3xl font-semibold tracking-[-0.02em]">
            Ready to protect your brand?
          </h2>
          <p className="mt-3 text-muted-foreground">
            See Dealer Intel in action with a personalized demo, or start exploring with a free trial.
          </p>
          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="mailto:sales@dealerintel.com"
              className="h-12 px-8 flex items-center justify-center bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 transition-all shadow-glow-lg gap-2 w-full sm:w-auto"
            >
              Book a Demo
              <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              href="/login"
              className="h-12 px-8 flex items-center justify-center border border-border text-foreground text-sm font-medium hover:bg-secondary transition-all w-full sm:w-auto"
            >
              Start Free Trial
            </Link>
          </div>
        </div>
      </section>

      <MarketingFooter />
    </div>
  );
}
