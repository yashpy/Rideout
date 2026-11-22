import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { THEME_SCRIPT } from "@/lib/theme";
import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist", display: "swap" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "RideOut", template: "%s · RideOut" },
  description: "Every home called. Every rider matched. Nobody told help is coming until a driver says yes.",
  manifest: "/manifest.webmanifest",
  applicationName: "RideOut",
  openGraph: {
    title: "RideOut: everyone gets a seat out of a wildfire",
    description:
      "Calls every home in the evacuation zone at once, finds who can't leave on their own, and dispatches responders and neighbors with a seat before the fire arrives.",
    type: "website",
    siteName: "RideOut",
  },
  twitter: { card: "summary_large_image", title: "RideOut", description: "Everyone gets a seat out." },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f7fa" },
    { media: "(prefers-color-scheme: dark)", color: "#090b14" },
  ],
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // data-theme is set before paint by THEME_SCRIPT, so React must not complain about it
    <html lang="en" suppressHydrationWarning className={`${geist.variable} ${geistMono.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
