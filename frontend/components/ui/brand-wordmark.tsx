import { cn } from "@/lib/utils";

interface BrandWordmarkProps {
  className?: string;
  showSubtitle?: boolean;
}

export function BrandWordmark({ className, showSubtitle }: BrandWordmarkProps) {
  return (
    <div>
      <span className={cn("font-display font-bold tracking-tight", className)}>
        DEALER <span className="text-accent">I</span>NTEL
      </span>
      {showSubtitle && (
        <p className="text-2xs uppercase tracking-widest text-muted-foreground">
          Asset Intelligence
        </p>
      )}
    </div>
  );
}

export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "font-display font-bold text-accent select-none",
        className
      )}
    >
      I
    </span>
  );
}
