"use client";

import { AudioLines, ChartBar, LogOut, MessageSquare, Settings, SquareKanban } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { NativeSelect } from "@/components/ui/input";
import { useAuth } from "@/lib/auth-context";
import { cn, initials } from "@/lib/utils";

const NAV = [
  { href: "/meetings", label: "Meetings", icon: AudioLines },
  { href: "/board", label: "Task board", icon: SquareKanban },
  { href: "/ask", label: "Ask", icon: MessageSquare },
  { href: "/dashboard", label: "Usage", icon: ChartBar },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, workspaces, workspace, selectWorkspace, logout } = useAuth();

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[15rem_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-card focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="hidden border-r bg-card/60 md:flex md:flex-col">
        <div className="flex h-14 items-center gap-2 px-5 font-semibold">
          <span className="grid size-7 place-items-center rounded-md bg-primary text-primary-foreground">
            <AudioLines className="size-4" aria-hidden />
          </span>
          MeetMind
        </div>
        <div className="px-3 pb-3">
          <label htmlFor="ws-switch" className="sr-only">
            Workspace
          </label>
          <NativeSelect
            id="ws-switch"
            className="w-full"
            value={workspace?.id ?? ""}
            onChange={(e) => selectWorkspace(e.target.value)}
          >
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </NativeSelect>
        </div>
        <nav aria-label="Main" className="flex flex-1 flex-col gap-0.5 px-3">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                  active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>
        <p className="px-5 py-4 text-xs text-muted-foreground">Role: {workspace?.role ?? "—"}</p>
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background/85 px-4 backdrop-blur">
          <span className="font-semibold md:hidden">MeetMind</span>
          <div className="ml-auto flex items-center gap-1">
            <ThemeToggle />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="Account menu" className="rounded-full">
                  <span className="grid size-8 place-items-center rounded-full bg-primary/15 text-xs font-semibold text-primary">
                    {initials(user?.name ?? "?")}
                  </span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>
                  <span className="block text-sm text-foreground">{user?.name}</span>
                  {user?.email}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={async () => {
                    await logout();
                    router.replace("/login");
                  }}
                >
                  <LogOut /> Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <nav aria-label="Main mobile" className="flex gap-1 overflow-x-auto border-b px-2 py-1.5 md:hidden">
          {NAV.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "shrink-0 rounded-md px-3 py-1.5 text-sm",
                pathname.startsWith(href) ? "bg-accent font-medium" : "text-muted-foreground",
              )}
            >
              {label}
            </Link>
          ))}
        </nav>
        <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
          {children}
        </main>
      </div>
    </div>
  );
}
