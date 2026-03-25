"use client";

import Link from "next/link";
import { Clock, ArrowRight, AlertTriangle } from "lucide-react";

interface TrialBannerProps {
  plan: string;
  planStatus: string;
  trialDaysLeft: number | null;
}

export function TrialBanner({ plan, planStatus, trialDaysLeft }: TrialBannerProps) {
  if (plan !== "free") return null;

  const expired = trialDaysLeft !== null && trialDaysLeft <= 0;
  const urgent = trialDaysLeft !== null && trialDaysLeft <= 3 && !expired;

  if (expired) {
    return (
      <div className="flex items-center gap-3 p-4 border border-destructive/30 bg-destructive/5 opacity-0 animate-fade-up">
        <AlertTriangle className="h-5 w-5 text-destructive flex-shrink-0" />
        <div className="flex-1">
          <p className="text-sm font-medium">Your free trial has expired</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            Book a demo to upgrade and continue using Dealer Intel.
          </p>
        </div>
        <Link
          href="mailto:sales@dealerintel.com"
          className="h-8 px-4 flex items-center justify-center bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 transition-colors shadow-glow gap-1.5 flex-shrink-0"
        >
          Book a Demo
          <ArrowRight className="h-3 w-3" />
        </Link>
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-3 p-4 border opacity-0 animate-fade-up ${
      urgent
        ? "border-amber-500/30 bg-amber-500/5"
        : "border-primary/20 bg-primary/5"
    }`}>
      <Clock className={`h-5 w-5 flex-shrink-0 ${urgent ? "text-amber-500" : "text-primary"}`} />
      <div className="flex-1">
        <p className="text-sm font-medium">
          Free trial{" "}
          {trialDaysLeft !== null ? (
            <>
              — <span className={`font-mono ${urgent ? "text-amber-500" : "text-primary"}`}>
                {trialDaysLeft}
              </span>{" "}
              {trialDaysLeft === 1 ? "day" : "days"} remaining
            </>
          ) : (
            "active"
          )}
        </p>
        <p className="text-xs text-muted-foreground mt-0.5">
          2 dealers, 1 campaign, 5 scans. Book a demo to unlock full access.
        </p>
      </div>
      <Link
        href="mailto:sales@dealerintel.com"
        className="h-8 px-4 flex items-center justify-center bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 transition-colors shadow-glow gap-1.5 flex-shrink-0"
      >
        Book a Demo
        <ArrowRight className="h-3 w-3" />
      </Link>
    </div>
  );
}
