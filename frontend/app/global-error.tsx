"use client";

import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Global error:", error);
    Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="en" className="dark">
      <body className="antialiased bg-zinc-950 text-zinc-100">
        <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-4">
          <div className="text-center">
            <h1 className="text-2xl font-bold">Application Error</h1>
            <p className="mt-2 text-zinc-400">
              A critical error occurred. Please try refreshing the page.
            </p>
            {error.digest && (
              <p className="mt-1 text-xs text-zinc-500">
                Error ID: {error.digest}
              </p>
            )}
          </div>
          <button
            onClick={reset}
            className="rounded-lg bg-zinc-800 px-4 py-2 text-sm font-medium transition-colors hover:bg-zinc-700"
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
