"use client";

import { usePathname } from "next/navigation";
import { AuthProvider, useAuth, PUBLIC_PATHS } from "@/lib/auth-context";
import { SidebarProvider } from "@/components/layout/sidebar-context";
import { Sidebar } from "@/components/layout/sidebar";
import { MainContent } from "@/components/layout/main-content";
import { UpgradeModalProvider } from "@/components/dashboard/upgrade-modal";
import { Loader2 } from "lucide-react";

function AuthenticatedShell({ children }: { children: React.ReactNode }) {
  const { loading, session } = useAuth();
  const pathname = usePathname();

  if (PUBLIC_PATHS.includes(pathname)) {
    return <>{children}</>;
  }

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!session) {
    return null;
  }

  return (
    <UpgradeModalProvider>
      <SidebarProvider>
        <div className="flex min-h-screen">
          <Sidebar />
          <MainContent>{children}</MainContent>
        </div>
      </SidebarProvider>
    </UpgradeModalProvider>
  );
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AuthenticatedShell>{children}</AuthenticatedShell>
    </AuthProvider>
  );
}
