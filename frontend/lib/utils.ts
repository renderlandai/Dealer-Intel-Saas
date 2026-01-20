import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(date: string | Date): string {
  return new Date(date).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatDateTime(date: string | Date): string {
  return new Date(date).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function timeAgo(date: string | Date): string {
  const now = new Date();
  const past = new Date(date);
  const diffMs = now.getTime() - past.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return formatDate(date);
}

export function getConfidenceColor(score: number): string {
  if (score >= 90) return "text-green-400";
  if (score >= 75) return "text-yellow-400";
  if (score >= 50) return "text-orange-400";
  return "text-red-400";
}

export function getMatchTypeBadge(type: string): { label: string; className: string } {
  const badges: Record<string, { label: string; className: string }> = {
    exact: { label: "Exact", className: "bg-green-500/20 text-green-400 border-green-500/30" },
    strong: { label: "Strong", className: "bg-blue-500/20 text-blue-400 border-blue-500/30" },
    partial: { label: "Partial", className: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" },
    weak: { label: "Weak", className: "bg-orange-500/20 text-orange-400 border-orange-500/30" },
  };
  return badges[type] || { label: type, className: "bg-gray-500/20 text-gray-400" };
}

export function getComplianceStatusBadge(status: string): { label: string; className: string } {
  const badges: Record<string, { label: string; className: string }> = {
    compliant: { label: "Compliant", className: "bg-green-500/20 text-green-400 border-green-500/30" },
    violation: { label: "Violation", className: "bg-red-500/20 text-red-400 border-red-500/30" },
    pending: { label: "Pending", className: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30" },
    review: { label: "In Review", className: "bg-blue-500/20 text-blue-400 border-blue-500/30" },
  };
  return badges[status] || { label: status, className: "bg-gray-500/20 text-gray-400" };
}

















