import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { QueryProvider } from "@/lib/query-provider";
import { AuthGate } from "@/components/layout/auth-gate";

// Self-hosted fonts (latin subset, variable weight axis) so a slow link to
// fonts.gstatic.com can't make Next.js's 3s font-fetch timeout fall back to
// the system stack. The .woff2 files live in `frontend/public/fonts/` and
// were sourced from Google Fonts (Inter v20, Plus Jakarta Sans v12,
// JetBrains Mono v24). To refresh them, re-download the latin subset URL
// from each family's `https://fonts.googleapis.com/css2?family=...` CSS.
const inter = localFont({
  src: "../public/fonts/Inter-latin-variable.woff2",
  variable: "--font-sans",
  display: "swap",
  weight: "100 900",
});

const jakarta = localFont({
  src: "../public/fonts/PlusJakartaSans-latin-variable.woff2",
  variable: "--font-display",
  display: "swap",
  weight: "200 800",
});

const mono = localFont({
  src: "../public/fonts/JetBrainsMono-latin-variable.woff2",
  variable: "--font-mono",
  display: "swap",
  weight: "100 800",
});

export const metadata: Metadata = {
  title: "Dealer Intel — Campaign Asset Intelligence",
  description: "AI-powered campaign asset monitoring for distributor networks",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      translate="no"
      className={`dark ${inter.variable} ${jakarta.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <meta name="google" content="notranslate" />
        <link
          href="https://api.mapbox.com/mapbox-gl-js/v3.3.0/mapbox-gl.css"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased" suppressHydrationWarning>
        <QueryProvider>
          <AuthGate>{children}</AuthGate>
        </QueryProvider>
      </body>
    </html>
  );
}
