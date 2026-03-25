"use client";

import { createContext, useContext, useState, useCallback, useEffect, ReactNode } from "react";
import { X, ShieldAlert, ArrowRight } from "lucide-react";
import { upgradeEvents } from "@/lib/upgrade-events";

interface UpgradeModalState {
  open: boolean;
  title: string;
  message: string;
}

interface UpgradeModalContextValue {
  showUpgradeModal: (title: string, message: string) => void;
}

const UpgradeModalContext = createContext<UpgradeModalContextValue | null>(null);

export function useUpgradeModal() {
  const ctx = useContext(UpgradeModalContext);
  if (!ctx) throw new Error("useUpgradeModal must be used within UpgradeModalProvider");
  return ctx;
}

export function UpgradeModalProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<UpgradeModalState>({
    open: false,
    title: "",
    message: "",
  });

  const showUpgradeModal = useCallback((title: string, message: string) => {
    setState({ open: true, title, message });
  }, []);

  useEffect(() => {
    const unsub = upgradeEvents.subscribe(({ title, message }) => {
      showUpgradeModal(title, message);
    });
    return unsub;
  }, [showUpgradeModal]);

  const close = useCallback(() => {
    setState((s) => ({ ...s, open: false }));
  }, []);

  return (
    <UpgradeModalContext.Provider value={{ showUpgradeModal }}>
      {children}
      {state.open && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={close} />
          <div className="relative w-full max-w-md mx-4 bg-card border border-border shadow-2xl animate-fade-up">
            <button
              onClick={close}
              className="absolute top-4 right-4 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="h-4 w-4" />
            </button>

            <div className="p-6 pt-8 text-center space-y-4">
              <div className="mx-auto w-12 h-12 flex items-center justify-center bg-primary/10 border border-primary/20">
                <ShieldAlert className="h-6 w-6 text-primary" />
              </div>

              <div className="space-y-2">
                <h3 className="text-lg font-semibold tracking-tight">
                  {state.title}
                </h3>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {state.message}
                </p>
              </div>

              <div className="flex flex-col gap-2 pt-2">
                <a
                  href="mailto:sales@dealerintel.com"
                  className="h-10 flex items-center justify-center gap-2 bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors shadow-glow"
                >
                  Book a Demo
                  <ArrowRight className="h-3.5 w-3.5" />
                </a>
                <button
                  onClick={close}
                  className="h-10 text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  Maybe later
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </UpgradeModalContext.Provider>
  );
}
