"use client";

import Link from "next/link";
import {
  ArrowRight,
  Globe,
  Brain,
  FileText,
  Clock,
  Bell,
  MapPin,
  Upload,
  Users,
  Radar,
  ChevronRight,
  Check,
  Zap,
  MessageSquare,
  Database,
  FolderSync,
  Megaphone,
  MonitorPlay,
  KanbanSquare,
} from "lucide-react";
import { MarketingNav } from "@/components/marketing/navbar";
import { MarketingFooter } from "@/components/marketing/footer";

const FEATURES = [
  {
    icon: Globe,
    title: "Multi-Channel Scanning",
    description:
      "Scan websites, Google Ads, Facebook, and Instagram for unauthorized or non-compliant use of your campaign assets.",
  },
  {
    icon: Brain,
    title: "Proprietary AI Detection",
    description:
      "Our multi-stage detection pipeline analyzes every discovered image using perceptual hashing, visual embeddings, and adaptive reasoning.",
  },
  {
    icon: FileText,
    title: "Compliance Reporting",
    description:
      "Generate branded PDF and CSV compliance reports. Share with stakeholders or attach to distributor performance reviews.",
  },
  {
    icon: Clock,
    title: "Automated Scheduling",
    description:
      "Set up recurring scans on daily, weekly, biweekly, or monthly cadences. Never miss a compliance issue again.",
  },
  {
    icon: Bell,
    title: "Real-Time Alerts",
    description:
      "Get email notifications the moment a violation is detected. Know about problems before your customers do.",
  },
  {
    icon: MapPin,
    title: "Dealer Network Map",
    description:
      "Visualize your entire distributor network with geospatial compliance data. Identify regional patterns instantly.",
  },
];

const STEPS = [
  {
    number: "01",
    icon: Upload,
    title: "Upload Your Assets",
    description:
      "Upload campaign creatives — logos, ads, banners, promotional images. These are the assets you need distributors to use correctly.",
  },
  {
    number: "02",
    icon: Users,
    title: "Add Your Dealers",
    description:
      "Import your distributor network with their websites and social media URLs. Bulk import or add one at a time.",
  },
  {
    number: "03",
    icon: Radar,
    title: "Scan & Monitor",
    description:
      "AI automatically scans every channel, detects your assets, evaluates compliance, and flags violations for your review.",
  },
];

const CHANNELS = [
  { name: "Websites", color: "bg-emerald-500" },
  { name: "Google Ads", color: "bg-amber-500" },
  { name: "Facebook", color: "bg-blue-500" },
  { name: "Instagram", color: "bg-pink-500" },
];

const INTEGRATIONS = [
  {
    category: "Communication",
    icon: MessageSquare,
    items: [
      { name: "Slack", live: true },
      { name: "Microsoft Teams", live: false },
    ],
  },
  {
    category: "CRM & Dealers",
    icon: Database,
    items: [
      { name: "Salesforce", live: true },
      { name: "HubSpot", live: false },
    ],
  },
  {
    category: "Asset Storage & DAM",
    icon: FolderSync,
    items: [
      { name: "Dropbox", live: true },
      { name: "Google Drive", live: false },
      { name: "SharePoint", live: false },
      { name: "Bynder", live: false },
      { name: "Brandfolder", live: false },
      { name: "Adobe Experience Manager", live: false },
      { name: "Frontify", live: false },
    ],
  },
  {
    category: "Project Management",
    icon: KanbanSquare,
    items: [
      { name: "Jira", live: true },
      { name: "Asana", live: false },
      { name: "Monday.com", live: false },
    ],
  },
  {
    category: "Co-op & Channel Marketing",
    icon: Megaphone,
    items: [
      { name: "Ansira", live: false },
      { name: "SproutLoud", live: false },
      { name: "BrandMuscle", live: false },
    ],
  },
  {
    category: "Ad Platforms",
    icon: MonitorPlay,
    items: [
      { name: "Google Ads", live: false },
      { name: "Meta Ads", live: false },
      { name: "YouTube", live: false },
      { name: "Microsoft Ads", live: false },
      { name: "TikTok Ads", live: false },
    ],
  },
];

const TIERS_PREVIEW = [
  {
    name: "Starter",
    tag: "Up to 10 dealers",
    description: "For small dealer networks getting started with compliance monitoring.",
    highlights: ["Website scanning", "15 scans / month", "Automated scheduling"],
  },
  {
    name: "Professional",
    tag: "Up to 40 dealers",
    popular: true,
    description: "For growing brands that need multi-channel visibility.",
    highlights: ["All 4 channels", "PDF reports & branding", "Email alerts"],
  },
  {
    name: "Business",
    tag: "Up to 100 dealers",
    description: "For established networks with high-volume monitoring needs.",
    highlights: ["150 scans / month", "Compliance trends", "10 user seats"],
  },
];

export default function LandingPage() {
  return (
    <div className="marketing-light min-h-screen bg-background text-foreground">
      <MarketingNav />

      {/* ─── Hero — Split Layout ─── */}
      <section
        className="relative pt-28 pb-20 overflow-hidden"
        style={{
          background: "linear-gradient(135deg, hsl(38 50% 95%) 0%, hsl(220 20% 96%) 35%, hsl(222 35% 90%) 100%)",
        }}
      >
        <div className="relative mx-auto max-w-7xl px-6">
          <div className="grid lg:grid-cols-2 gap-12 lg:gap-16 items-center">
            {/* Left — Copy */}
            <div className="max-w-xl">
              <div className="inline-flex items-center gap-2 border border-accent/20 bg-accent/5 px-3 py-1 text-2xs font-mono font-medium uppercase tracking-wide text-accent mb-6 opacity-0 animate-fade-up" style={{ animationFillMode: "forwards" }}>
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                14-Day Free Trial
              </div>

              <h1 className="font-display text-4xl sm:text-5xl lg:text-6xl font-bold tracking-[-0.025em] leading-[1.08] opacity-0 animate-fade-up delay-75" style={{ animationFillMode: "forwards" }}>
                Dealer Intelligence.{" "}
                <span className="text-accent">Campaign Compliance.</span>
              </h1>

              <p className="mt-6 text-lg leading-relaxed text-muted-foreground opacity-0 animate-fade-up delay-150" style={{ animationFillMode: "forwards" }}>
                Automatically detect how distributors use your brand assets
                across websites, Google Ads, Facebook, and Instagram.
              </p>

              <div className="mt-8 flex flex-col sm:flex-row items-start gap-4 opacity-0 animate-fade-up delay-225" style={{ animationFillMode: "forwards" }}>
                <Link
                  href="mailto:sales@dealerintel.com"
                  className="h-12 px-8 flex items-center justify-center bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 transition-all rounded-md gap-2"
                >
                  Request Demo
                  <ArrowRight className="h-4 w-4" />
                </Link>
                <Link
                  href="/login"
                  className="h-12 px-8 flex items-center justify-center text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
                >
                  or start a free trial
                </Link>
              </div>

              {/* Channel pills */}
              <div className="mt-10 flex items-center gap-3 flex-wrap opacity-0 animate-fade-up delay-300" style={{ animationFillMode: "forwards" }}>
                {CHANNELS.map((ch) => (
                  <div
                    key={ch.name}
                    className="flex items-center gap-2 text-xs text-muted-foreground"
                  >
                    <div className={`w-2 h-2 rounded-full ${ch.color}`} />
                    {ch.name}
                  </div>
                ))}
              </div>
            </div>

            {/* Right — Product Screenshot */}
            <div className="relative opacity-0 animate-fade-up delay-300" style={{ animationFillMode: "forwards" }}>
              <div
                className="absolute -inset-8 rounded-full pointer-events-none"
                style={{
                  background: "radial-gradient(ellipse at 50% 50%, hsl(222 55% 82% / 0.5) 0%, transparent 70%)",
                  animation: "glow-breathe 5s ease-in-out infinite",
                }}
              />
              <div className="relative">
                <div className="rounded-lg overflow-hidden border border-border shadow-2xl shadow-black/10">
                  <img
                    src="/dashboard-preview.png"
                    alt="Dealer Intel Dashboard"
                    className="w-full h-auto block"
                  />
                </div>
                <div className="absolute -bottom-4 -left-4 -right-4 h-24 bg-gradient-to-t from-[hsl(222_35%_90%)] to-transparent pointer-events-none" />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Stats Strip ─── */}
      <section className="border-y border-border bg-card/50">
        <div className="mx-auto max-w-7xl grid grid-cols-2 md:grid-cols-4 divide-x divide-border">
          {[
            { value: "4", label: "Channels Monitored" },
            { value: "Smart", label: "Visual Detection" },
            { value: "< 5 min", label: "Setup Time" },
            { value: "24/7", label: "Automated Scanning" },
          ].map((stat) => (
            <div key={stat.label} className="py-10 px-6 text-center">
              <p className="font-mono text-3xl font-semibold tracking-tight text-accent">{stat.value}</p>
              <p className="mt-2 text-2xs text-muted-foreground uppercase tracking-wider">
                {stat.label}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ─── Connections Marquee ─── */}
      <section className="py-14 overflow-hidden">
        <p className="text-center text-2xs font-semibold uppercase tracking-wider text-muted-foreground mb-10">
          Connects to the tools you already use
        </p>
        <div
          className="flex w-max hover:[animation-play-state:paused]"
          style={{ animation: "marquee 20s linear infinite" }}
        >
          {[0, 1].map((copy) => (
            <div key={copy} className="flex items-center gap-16 px-8" aria-hidden={copy === 1}>
              {/* Slack */}
              <div className="flex items-center gap-2.5 text-[#4A154B] shrink-0">
                <svg width="28" height="28" viewBox="0 0 128 128" fill="none">
                  <path d="M26.9 80.4c0 7.4-6.1 13.4-13.4 13.4S0 87.8 0 80.4c0-7.4 6.1-13.4 13.4-13.4h13.4v13.4zm6.8 0c0-7.4 6.1-13.4 13.4-13.4s13.4 6.1 13.4 13.4v33.6c0 7.4-6.1 13.4-13.4 13.4s-13.4-6.1-13.4-13.4V80.4z" fill="#E01E5A"/>
                  <path d="M47.1 26.9c-7.4 0-13.4-6.1-13.4-13.4S39.7 0 47.1 0s13.4 6.1 13.4 13.4v13.4H47.1zm0 6.8c7.4 0 13.4 6.1 13.4 13.4s-6.1 13.4-13.4 13.4H13.4C6.1 60.5 0 54.5 0 47.1s6.1-13.4 13.4-13.4h33.7z" fill="#36C5F0"/>
                  <path d="M100.9 47.1c0-7.4 6.1-13.4 13.4-13.4 7.4 0 13.4 6.1 13.4 13.4s-6.1 13.4-13.4 13.4h-13.4V47.1zm-6.8 0c0 7.4-6.1 13.4-13.4 13.4-7.4 0-13.4-6.1-13.4-13.4V13.4C67.3 6.1 73.4 0 80.7 0c7.4 0 13.4 6.1 13.4 13.4v33.7z" fill="#2EB67D"/>
                  <path d="M80.7 100.9c7.4 0 13.4 6.1 13.4 13.4 0 7.4-6.1 13.4-13.4 13.4-7.4 0-13.4-6.1-13.4-13.4v-13.4h13.4zm0-6.8c-7.4 0-13.4-6.1-13.4-13.4 0-7.4 6.1-13.4 13.4-13.4h33.6c7.4 0 13.4 6.1 13.4 13.4 0 7.4-6.1 13.4-13.4 13.4H80.7z" fill="#ECB22E"/>
                </svg>
                <span className="text-lg font-semibold tracking-tight">Slack</span>
              </div>

              {/* Salesforce */}
              <div className="flex items-center gap-2 shrink-0">
                <svg width="36" height="25" viewBox="0 0 60 42" fill="none">
                  <path d="M24.9 4.8c2.4-2.5 5.8-4 9.5-4 5 0 9.3 2.7 11.7 6.7 2.1-0.9 4.3-1.5 6.7-1.5C60.6 6 67 12.4 67 20.2S60.6 34.4 52.8 34.4c-1 0-2-.1-3-.3-2.1 3.5-5.9 5.8-10.3 5.8-2 0-3.9-.5-5.5-1.4-2.1 3.9-6.2 6.5-10.9 6.5-5.2 0-9.6-3.2-11.5-7.7-1 .3-2.1.4-3.2.4C3.7 37.7 0 30.5 0 25.7 0 20 4.7 15 10.5 14.4c-.1-.8-.2-1.6-.2-2.4 0-6.6 5.4-12 12-12 4 0 7.5 2 9.7 5z" fill="#00A1E0" transform="scale(0.85) translate(2,2)"/>
                </svg>
                <span className="text-lg font-semibold tracking-tight text-[#00A1E0]">Salesforce</span>
              </div>

              {/* Dropbox */}
              <div className="flex items-center gap-2 text-[#0061FF] shrink-0">
                <svg width="26" height="24" viewBox="0 0 43 40" fill="currentColor">
                  <path d="M12.6 0L0 8.1l8.7 7 12.8-7.9L12.6 0zM0 22.1l12.6 8.1 8.9-6.9-12.8-7.9L0 22.1zM21.5 23.3l8.9 6.9 12.6-8.1-8.7-7-12.8 8.2zM43 8.1L30.4 0l-8.9 7.2 12.8 7.9L43 8.1zM21.5 25.4l-8.9 6.9-3.7-2.4v2.7l12.6 7.5 12.6-7.5v-2.7l-3.7 2.4-8.9-6.9z"/>
                </svg>
                <span className="text-lg font-semibold tracking-tight">Dropbox</span>
              </div>

              {/* Jira */}
              <div className="flex items-center gap-2.5 shrink-0">
                <svg width="28" height="28" viewBox="0 0 256 256" fill="none">
                  <defs>
                    <linearGradient id={`jira-a-${copy}`} x1="102.4" y1="218.2" x2="56.6" y2="172.4">
                      <stop stopColor="#0052CC"/>
                      <stop offset="0.92" stopColor="#2684FF"/>
                    </linearGradient>
                    <linearGradient id={`jira-b-${copy}`} x1="114.7" y1="85.8" x2="160.5" y2="131.7">
                      <stop stopColor="#0052CC"/>
                      <stop offset="0.92" stopColor="#2684FF"/>
                    </linearGradient>
                  </defs>
                  <path d="M244.7 0H121.3c0 34.2 27.8 61.9 62 61.9h20.3v19.6c0 34.2 27.7 62 61.9 62V11.2A11.2 11.2 0 00244.7 0z" fill="#2684FF"/>
                  <path d="M183 62.9H59.7C59.7 97 87.4 124.8 121.6 124.8h20.4v19.6c0 34.1 27.7 61.9 61.9 61.9V74.1A11.2 11.2 0 00183 62.9z" fill={`url(#jira-b-${copy})`}/>
                  <path d="M121.3 125.7H-2c0 34.2 27.7 62 61.9 62h20.4v19.6c0 34.1 27.7 61.9 61.9 61.9V136.9a11.2 11.2 0 00-10.9-11.2z" fill={`url(#jira-a-${copy})`}/>
                </svg>
                <span className="text-lg font-semibold tracking-tight text-[#253858]">Jira</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ─── Features ─── */}
      <section id="features" className="py-24">
        <div className="mx-auto max-w-7xl px-6">
          <div className="text-center mb-16">
            <p className="text-2xs font-semibold uppercase tracking-wider text-accent mb-3">
              Features
            </p>
            <h2 className="font-display text-3xl md:text-4xl font-bold tracking-[-0.025em]">
              Everything you need to protect your brand
            </h2>
            <p className="mt-4 text-muted-foreground max-w-xl mx-auto leading-relaxed">
              From automated scanning to AI-powered analysis, Dealer Intel gives
              you complete visibility into how your marketing assets are being
              used.
            </p>
          </div>

          <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((feature) => (
              <div
                key={feature.title}
                className="p-6 border border-border bg-background rounded-md group hover-lift"
              >
                <div className="flex h-10 w-10 items-center justify-center mb-4 bg-primary/10 border border-primary/20 rounded-md">
                  <feature.icon className="h-5 w-5 text-primary" />
                </div>
                <h3 className="text-base font-semibold mb-2">
                  {feature.title}
                </h3>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {feature.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── How It Works ─── */}
      <section id="how-it-works" className="py-24 border-y border-border bg-card/30">
        <div className="mx-auto max-w-7xl px-6">
          <div className="text-center mb-16">
            <p className="text-2xs font-semibold uppercase tracking-wider text-accent mb-3">
              How It Works
            </p>
            <h2 className="font-display text-3xl md:text-4xl font-bold tracking-[-0.025em]">
              Up and running in minutes
            </h2>
            <p className="mt-4 text-muted-foreground max-w-xl mx-auto leading-relaxed">
              Three steps from signup to your first compliance scan. No
              engineering team required.
            </p>
          </div>

          <div className="grid gap-8 md:grid-cols-3">
            {STEPS.map((step, i) => (
              <div key={step.number} className="relative">
                {i < STEPS.length - 1 && (
                  <div className="hidden md:block absolute top-12 left-full w-full h-px">
                    <div className="w-full h-px bg-gradient-to-r from-border via-primary/30 to-border" />
                    <ChevronRight className="absolute -right-2 -top-1.5 h-3 w-3 text-primary/40" />
                  </div>
                )}

                <div className="text-center">
                  <div className="inline-flex items-center justify-center relative mb-6">
                    <div className="flex h-16 w-16 items-center justify-center bg-background border border-border rounded-md">
                      <step.icon className="h-7 w-7 text-primary" />
                    </div>
                    <span className="absolute -top-2 -right-2 flex h-6 w-6 items-center justify-center bg-primary text-primary-foreground text-2xs font-bold rounded-md">
                      {step.number}
                    </span>
                  </div>
                  <h3 className="font-display text-lg font-semibold mb-2">{step.title}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed max-w-xs mx-auto">
                    {step.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── Trust / Why Us ─── */}
      <section className="py-24">
        <div className="mx-auto max-w-7xl px-6">
          <div className="grid gap-6 md:grid-cols-3">
            {[
              {
                icon: Clock,
                title: "Set It and Forget It",
                description:
                  "Schedule scans on any cadence — daily, weekly, or monthly. Violations trigger alerts to Slack, Jira, and email automatically. You only see problems that need your attention.",
              },
              {
                icon: Zap,
                title: "Built for Scale",
                description:
                  "Distributed task queue with crash recovery. Scan hundreds of dealers across four channels without breaking a sweat.",
              },
              {
                icon: Brain,
                title: "Adaptive Detection Engine",
                description:
                  "Our detection engine learns from your feedback. Thumbs-up or down on matches to calibrate thresholds for your brand.",
              },
            ].map((item) => (
              <div
                key={item.title}
                className="p-8 text-center border border-border bg-background rounded-md"
              >
                <div className="inline-flex h-12 w-12 items-center justify-center mb-4 bg-primary/10 border border-primary/20 rounded-md">
                  <item.icon className="h-6 w-6 text-primary" />
                </div>
                <h3 className="text-base font-semibold mb-2">{item.title}</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {item.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── Integrations ─── */}
      <section id="integrations" className="py-24 border-y border-border bg-card/30">
        <div className="mx-auto max-w-7xl px-6">
          <div className="text-center mb-16">
            <p className="text-2xs font-semibold uppercase tracking-wider text-accent mb-3">
              Integrations
            </p>
            <h2 className="font-display text-3xl md:text-4xl font-bold tracking-[-0.025em]">
              Connects to your existing stack
            </h2>
            <p className="mt-4 text-muted-foreground max-w-xl mx-auto leading-relaxed">
              Push violations to Slack, sync dealers from Salesforce, auto-import
              assets from Dropbox, create Jira tickets — and more on the way.
            </p>
          </div>

          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {INTEGRATIONS.map((group) => (
              <div
                key={group.category}
                className="p-5 border border-border bg-background rounded-md"
              >
                <div className="flex items-center gap-2.5 mb-4">
                  <div className="flex h-8 w-8 items-center justify-center bg-primary/10 border border-primary/20 rounded-md">
                    <group.icon className="h-4 w-4 text-primary" />
                  </div>
                  <h3 className="text-sm font-semibold">{group.category}</h3>
                </div>
                <ul className="space-y-2">
                  {group.items.map((item) => (
                    <li key={item.name} className="flex items-center justify-between">
                      <span className="text-sm text-foreground/80">{item.name}</span>
                      {item.live ? (
                        <span className="inline-flex items-center gap-1 text-2xs font-medium text-emerald-600">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                          Live
                        </span>
                      ) : (
                        <span className="text-2xs text-muted-foreground">
                          Coming soon
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── Pricing Preview ─── */}
      <section className="py-24">
        <div className="mx-auto max-w-7xl px-6">
          <div className="text-center mb-16">
            <h2 className="font-display text-3xl md:text-4xl font-bold tracking-[-0.025em]">
              Plans that scale with your network
            </h2>
            <p className="mt-4 text-muted-foreground max-w-xl mx-auto leading-relaxed">
              Start with a free trial. Upgrade when you&apos;re ready. Every plan
              includes core scanning and AI detection.
            </p>
          </div>

          <div className="grid gap-6 md:grid-cols-3 max-w-5xl mx-auto">
            {TIERS_PREVIEW.map((tier) => (
              <div
                key={tier.name}
                className={`relative p-8 border bg-background rounded-md ${
                  tier.popular
                    ? "border-primary/50 shadow-lg shadow-primary/10"
                    : "border-border"
                }`}
              >
                {tier.popular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 bg-primary text-primary-foreground text-2xs font-semibold uppercase tracking-wider rounded-sm">
                    Most Popular
                  </div>
                )}

                <h3 className="font-display text-lg font-semibold">{tier.name}</h3>
                <p className="mt-2 text-sm font-mono text-accent">{tier.tag}</p>
                <p className="mt-3 text-sm text-muted-foreground leading-relaxed">
                  {tier.description}
                </p>

                <ul className="mt-6 space-y-3">
                  {tier.highlights.map((h) => (
                    <li key={h} className="flex items-center gap-2 text-sm">
                      <Check className="h-3.5 w-3.5 text-primary flex-shrink-0" />
                      <span className="text-foreground/80">{h}</span>
                    </li>
                  ))}
                </ul>

                <Link
                  href="mailto:sales@dealerintel.com"
                  className={`mt-8 h-10 w-full flex items-center justify-center text-sm font-medium transition-all rounded-md ${
                    tier.popular
                      ? "bg-primary text-primary-foreground hover:bg-primary/90"
                      : "border border-border hover:border-primary/40 hover:bg-primary/5 text-foreground"
                  }`}
                >
                  Book a Demo
                </Link>
              </div>
            ))}
          </div>

          <div className="mt-10 text-center">
            <Link
              href="/pricing"
              className="inline-flex items-center gap-1.5 text-sm text-accent hover:text-accent/80 transition-colors font-medium"
            >
              Compare all plans in detail
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </section>

      {/* ─── Final CTA ─── */}
      <section className="py-24">
        <div className="mx-auto max-w-3xl px-6 text-center">
          <h2 className="font-display text-3xl md:text-4xl font-bold tracking-[-0.025em]">
            Start monitoring your dealer
            <br className="hidden sm:block" /> network today
          </h2>
          <p className="mt-4 text-muted-foreground max-w-lg mx-auto leading-relaxed">
            See how Dealer Intel can protect your brand with a personalized
            demo, or explore the platform with a free trial.
          </p>
          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="mailto:sales@dealerintel.com"
              className="h-12 px-8 flex items-center justify-center bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 transition-all rounded-md gap-2 w-full sm:w-auto"
            >
              Book a Demo
              <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              href="/login"
              className="h-12 px-8 flex items-center justify-center border border-border text-foreground text-sm font-medium hover:border-primary/40 hover:bg-primary/5 transition-all rounded-md w-full sm:w-auto"
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
