import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { NavBar } from "@/components/nav-bar";

export const metadata: Metadata = {
  title: "Sears Home Services",
  description: "Voice diagnostic agent for home appliances.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark font-sans">
      <body className="flex h-screen flex-col bg-background text-foreground">
        <NavBar />
        {children}
      </body>
    </html>
  );
}
