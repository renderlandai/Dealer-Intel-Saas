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
  Shield,
  ChevronRight,
  Check,
  Zap,
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
      "Our proprietary multi-stage detection pipeline analyzes every discovered image against your campaign assets using perceptual hashing, visual embeddings, and adaptive reasoning.",
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
  { name: "Websites", color: "bg-emerald-500", glow: "shadow-[0_0_12px_hsl(158_64%_42%/0.4)]" },
  { name: "Google Ads", color: "bg-amber-500", glow: "shadow-[0_0_12px_hsl(38_92%_55%/0.4)]" },
  { name: "Facebook", color: "bg-blue-500", glow: "shadow-[0_0_12px_hsl(217_91%_60%/0.4)]" },
  { name: "Instagram", color: "bg-pink-500", glow: "shadow-[0_0_12px_hsl(330_81%_60%/0.4)]" },
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
    <div className="min-h-screen bg-background">
      <MarketingNav />

      {/* ─── Hero ─── */}
      <section className="relative pt-32 pb-28 overflow-hidden">
        <div className="absolute inset-0 grid-bg opacity-30" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] rounded-full bg-primary/[0.04] blur-[120px]" />

        <div className="relative mx-auto max-w-5xl px-6 text-center">
          <div className="inline-flex items-center gap-2.5 border border-primary/20 bg-primary/5 px-4 py-1.5 text-2xs font-mono font-medium uppercase tracking-[0.05em] text-primary mb-8 opacity-0 animate-fade-up">
            <span className="status-dot active" />
            14-Day Free Trial — No Credit Card Required
          </div>

          <h1 className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-semibold tracking-[-0.02em] leading-[1.1] opacity-0 animate-fade-up delay-75">
            Dealer Intelligence.
            <br />
            <span className="text-primary">Campaign Compliance.</span>
          </h1>

          <p className="mt-6 text-base sm:text-lg max-w-2xl mx-auto leading-[1.6] opacity-0 animate-fade-up delay-150" style={{ color: '#A1A1AA' }}>
            Automatically detect how distributors use your brand assets
            across websites, Google Ads, Facebook, and Instagram. Full
            visibility into every channel, every dealer.
          </p>

          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4 opacity-0 animate-fade-up delay-225">
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

          {/* Channel pills */}
          <div className="mt-16 flex items-center justify-center gap-3 flex-wrap opacity-0 animate-fade-up delay-300">
            {CHANNELS.map((ch) => (
              <div
                key={ch.name}
                className="flex items-center gap-2 px-3 py-1.5 border border-border bg-card/60 text-xs text-muted-foreground"
              >
                <div className={`w-2 h-2 ${ch.color} ${ch.glow}`} />
                {ch.name}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── Stats Strip ─── */}
      <section className="border-y border-border bg-card/50">
        <div className="mx-auto max-w-7xl grid grid-cols-2 md:grid-cols-4 divide-x divide-border">
          {[
            { value: "4", label: "Channels Monitored" },
            { value: "99.2%", label: "Detection Accuracy" },
            { value: "< 5 min", label: "Setup Time" },
            { value: "24/7", label: "Automated Scanning" },
          ].map((stat) => (
            <div key={stat.label} className="py-10 px-6 text-center">
              <p className="data-value text-primary">{stat.value}</p>
              <p className="mt-2 text-2xs text-muted-foreground uppercase tracking-wider">
                {stat.label}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ─── Features ─── */}
      <section id="features" className="py-28 relative">
        <div className="mx-auto max-w-7xl px-6">
          <div className="text-center mb-16">
            <p className="text-2xs font-semibold uppercase tracking-wider text-primary mb-3">
              Features
            </p>
            <h2 className="text-3xl md:text-4xl font-semibold tracking-[-0.02em]">
              Everything you need to protect your brand
            </h2>
            <p className="mt-4 text-muted-foreground max-w-xl mx-auto leading-relaxed">
              From automated scanning to AI-powered analysis, Dealer Intel gives
              you complete visibility into how your marketing assets are being
              used.
            </p>
          </div>

          <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((feature, i) => (
              <div
                key={feature.title}
                className="card-sharp p-6 group hover-lift opacity-0 animate-fade-up"
                style={{
                  animationDelay: `${100 + i * 75}ms`,
                  animationFillMode: "forwards",
                }}
              >
                <div className="flex h-10 w-10 items-center justify-center bg-primary/10 border border-primary/20 mb-4">
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
      <section
        id="how-it-works"
        className="py-28 border-y border-border section-gradient"
      >
        <div className="mx-auto max-w-7xl px-6">
          <div className="text-center mb-16">
            <p className="text-2xs font-semibold uppercase tracking-wider text-primary mb-3">
              How It Works
            </p>
            <h2 className="text-3xl md:text-4xl font-semibold tracking-[-0.02em]">
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
                    <div className="flex h-16 w-16 items-center justify-center bg-card border border-border">
                      <step.icon className="h-7 w-7 text-primary" />
                    </div>
                    <span className="absolute -top-2 -right-2 flex h-6 w-6 items-center justify-center bg-primary text-primary-foreground text-2xs font-bold">
                      {step.number}
                    </span>
                  </div>
                  <h3 className="text-lg font-semibold mb-2">{step.title}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed max-w-xs mx-auto">
                    {step.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── Social Proof / Trust ─── */}
      <section className="py-28">
        <div className="mx-auto max-w-7xl px-6">
          <div className="grid gap-6 md:grid-cols-3">
            {[
              {
                icon: Shield,
                title: "Enterprise-Grade Security",
                description:
                  "TLS-encrypted connections, role-based access control, and isolated tenant data. Built for teams that take security seriously.",
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
                  "Our proprietary detection engine learns from your feedback. Thumbs-up or down on matches to calibrate thresholds for your brand.",
              },
            ].map((item, i) => (
              <div
                key={item.title}
                className="stat-card p-8 text-center opacity-0 animate-fade-up"
                style={{
                  animationDelay: `${100 + i * 100}ms`,
                  animationFillMode: "forwards",
                }}
              >
                <div className="inline-flex h-12 w-12 items-center justify-center bg-primary/10 border border-primary/20 mb-4">
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

      {/* ─── Pricing Preview ─── */}
      <section className="py-28 border-y border-border section-gradient">
        <div className="mx-auto max-w-7xl px-6">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-semibold tracking-[-0.02em]">
              Plans that scale with your network
            </h2>
            <p className="mt-4 text-muted-foreground max-w-xl mx-auto leading-relaxed">
              Start with a free trial. Upgrade when you&apos;re ready. Every plan
              includes core scanning and AI detection.
            </p>
          </div>

          <div className="grid gap-6 md:grid-cols-3 max-w-5xl mx-auto">
            {TIERS_PREVIEW.map((tier, i) => (
              <div
                key={tier.name}
                className={`relative p-8 border bg-card opacity-0 animate-fade-up ${
                  tier.popular
                    ? "border-primary/50 shadow-glow"
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
                <p className="mt-2 text-sm font-mono text-primary">{tier.tag}</p>
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
                  className={`mt-8 h-10 w-full flex items-center justify-center text-sm font-medium transition-all ${
                    tier.popular
                      ? "bg-primary text-primary-foreground hover:bg-primary/90 shadow-glow"
                      : "border border-border hover:bg-secondary hover:text-foreground"
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
              className="inline-flex items-center gap-1.5 text-sm text-primary hover:text-primary/80 transition-colors font-medium"
            >
              Compare all plans in detail
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </section>

      {/* ─── Final CTA ─── */}
      <section className="py-28 relative overflow-hidden">
        <div className="absolute inset-0 grid-bg opacity-20" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-primary/[0.03] blur-[100px]" />

        <div className="relative mx-auto max-w-3xl px-6 text-center">
          <h2 className="text-3xl md:text-4xl font-semibold tracking-[-0.02em]">
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
