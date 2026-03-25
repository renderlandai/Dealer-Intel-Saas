"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Megaphone,
  Upload,
  Building2,
  ScanSearch,
  Check,
  ArrowRight,
  X,
  Rocket,
} from "lucide-react";

interface OnboardingStep {
  id: string;
  label: string;
  description: string;
  href: string;
  icon: React.ElementType;
  complete: boolean;
}

interface OnboardingChecklistProps {
  campaignCount: number;
  assetCount: number;
  distributorCount: number;
  scanCount: number;
}

export function OnboardingChecklist({
  campaignCount,
  assetCount,
  distributorCount,
  scanCount,
}: OnboardingChecklistProps) {
  const [dismissed, setDismissed] = useState(false);

  const steps: OnboardingStep[] = [
    {
      id: "campaign",
      label: "Create a campaign",
      description: "Define the creative assets you want to track across your dealer network.",
      href: "/campaigns",
      icon: Megaphone,
      complete: campaignCount > 0,
    },
    {
      id: "assets",
      label: "Upload campaign assets",
      description: "Add the images and creatives your dealers should be running.",
      href: "/campaigns",
      icon: Upload,
      complete: assetCount > 0,
    },
    {
      id: "dealer",
      label: "Add a dealer",
      description: "Register a distributor with their website or social channels.",
      href: "/distributors",
      icon: Building2,
      complete: distributorCount > 0,
    },
    {
      id: "scan",
      label: "Run your first scan",
      description: "Scan a dealer's channels to detect your campaign assets.",
      href: "/scans",
      icon: ScanSearch,
      complete: scanCount > 0,
    },
  ];

  const completedCount = steps.filter((s) => s.complete).length;
  const allComplete = completedCount === steps.length;

  if (dismissed || allComplete) return null;

  const pct = (completedCount / steps.length) * 100;
  const nextStep = steps.find((s) => !s.complete);

  return (
    <div className="border border-border bg-card p-6 space-y-5 opacity-0 animate-fade-up" style={{ animationFillMode: "forwards" }}>
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center bg-primary">
            <Rocket className="h-5 w-5 text-primary-foreground" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-tight">Get started with Dealer Intel</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Complete these steps to start monitoring your dealer network.
            </p>
          </div>
        </div>
        <button
          onClick={() => setDismissed(true)}
          className="text-muted-foreground hover:text-foreground transition-colors p-1"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Progress bar */}
      <div className="space-y-1.5">
        <div className="flex justify-between text-2xs text-muted-foreground">
          <span>{completedCount} of {steps.length} complete</span>
          <span className="font-mono">{Math.round(pct)}%</span>
        </div>
        <div className="h-1.5 w-full bg-secondary rounded-full overflow-hidden">
          <div
            className="h-full bg-primary rounded-full transition-all duration-500"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Steps */}
      <div className="space-y-1">
        {steps.map((step, i) => (
          <Link
            key={step.id}
            href={step.complete ? "#" : step.href}
            className={`group flex items-center gap-3 p-3 transition-all ${
              step.complete
                ? "opacity-60"
                : nextStep?.id === step.id
                ? "bg-primary/5 border border-primary/20"
                : "hover:bg-secondary/50"
            }`}
            onClick={step.complete ? (e) => e.preventDefault() : undefined}
          >
            <div className={`flex h-8 w-8 items-center justify-center flex-shrink-0 ${
              step.complete
                ? "bg-success/10 border border-success/20"
                : nextStep?.id === step.id
                ? "bg-primary/10 border border-primary/20"
                : "bg-secondary border border-border"
            }`}>
              {step.complete ? (
                <Check className="h-4 w-4 text-success" />
              ) : (
                <step.icon className={`h-4 w-4 ${
                  nextStep?.id === step.id ? "text-primary" : "text-muted-foreground"
                }`} />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <p className={`text-sm font-medium ${step.complete ? "line-through text-muted-foreground" : ""}`}>
                {step.label}
              </p>
              {nextStep?.id === step.id && (
                <p className="text-xs text-muted-foreground mt-0.5">{step.description}</p>
              )}
            </div>
            {!step.complete && nextStep?.id === step.id && (
              <ArrowRight className="h-4 w-4 text-primary flex-shrink-0 group-hover:translate-x-0.5 transition-transform" />
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}
