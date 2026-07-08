"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Headset } from "lucide-react";
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
} from "@/components/ui/navigation-menu";

const NAV_LINKS = [{ href: "/", label: "Diagnostic Chat" }];

export function NavBar() {
  const pathname = usePathname();

  return (
    <header className="flex shrink-0 items-center justify-between border-b bg-background px-5 py-3">
      <Link href="/" className="flex items-center gap-2 font-semibold">
        <Headset className="size-5 text-primary" />
        Sears Home Services
      </Link>
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
    </header>
  );
}
