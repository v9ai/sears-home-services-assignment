import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sears Home Services",
  description: "Voice diagnostic agent for home appliances.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark font-sans">
      <body>{children}</body>
    </html>
  );
}
