import type { Metadata, Viewport } from "next";
import "./globals.css";

export const viewport: Viewport = {
  themeColor: "#ffab01",
};

export const metadata: Metadata = {
  title: "peon-ping — Stop babysitting your terminal",
  description:
    "Game character voice lines as notifications for Claude Code, Codex, Cursor, Antigravity & more. Never miss when your AI agent needs you.",
  openGraph: {
    title: "peon-ping — Stop babysitting your terminal",
    description:
      "Game character voice lines as notifications for Claude Code, Codex, Cursor, Antigravity & more. Never miss when your AI agent needs you.",
    type: "website",
    url: "https://peonping.com/",
    images: ["https://peonping.com/images/og-image.png"],
  },
  twitter: {
    card: "summary_large_image",
    images: ["https://peonping.com/images/og-image.png"],
  },
  icons: {
    icon: "/images/peon-icon.png",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
