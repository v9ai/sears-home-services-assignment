"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Headset, Phone } from "lucide-react";
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
} from "@/components/ui/navigation-menu";

const NAV_LINKS = [
  { href: "/", label: "Diagnostic Chat" },
  { href: "/recordings", label: "Recordings" },
];

// Twilio Programmable Voice number (specs/features/2026-07-08-telephony-twilio) — inbound only.
const SUPPORT_PHONE_NUMBER = "+13186468479";
const SUPPORT_PHONE_DISPLAY = "(318) 646-8479";

export function NavBar() {
  const pathname = usePathname();

  return (
    <header className="flex shrink-0 items-center justify-between border-b bg-background px-5 py-3">
      <Link href="/" className="flex items-center gap-2 font-semibold">
        <Headset className="size-5 text-primary" />
        Sears Home Services
      </Link>
      <div className="flex items-center gap-4">
        <NavigationMenu>
          <NavigationMenuList>
            {NAV_LINKS.map((link) => (
              <NavigationMenuItem key={link.href}>
                <NavigationMenuLink active={pathname === link.href} render={<Link href={link.href} />}>
                  {link.label}
                </NavigationMenuLink>
              </NavigationMenuItem>
            ))}
          </NavigationMenuList>
        </NavigationMenu>
        <a
          href={`tel:${SUPPORT_PHONE_NUMBER}`}
          className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          <Phone className="size-4 text-primary" />
          {SUPPORT_PHONE_DISPLAY}
        </a>
      </div>
    </header>
  );
}
