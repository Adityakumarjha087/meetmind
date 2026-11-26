"use client";

import { AskChat } from "@/components/ask-chat";
import { useAuth } from "@/lib/auth-context";

export default function AskPage() {
  const { workspace } = useAuth();
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Ask your meetings</h1>
        <p className="text-sm text-muted-foreground">Semantic search across every transcript in {workspace!.name}, with timestamped citations.</p>
      </div>
      <AskChat key={workspace!.id} workspaceId={workspace!.id} />
    </div>
  );
}
