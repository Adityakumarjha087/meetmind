import { Badge } from "@/components/ui/badge";
import type { MeetingStatus } from "@/lib/types";

const MAP: Record<MeetingStatus, { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" | "outline" }> = {
  scheduled: { label: "Scheduled", variant: "outline" },
  queued: { label: "Queued", variant: "secondary" },
  processing: { label: "Processing", variant: "warning" },
  completed: { label: "Ready", variant: "success" },
  failed: { label: "Failed", variant: "destructive" },
};

export function StatusBadge({ status }: { status: MeetingStatus }) {
  const s = MAP[status];
  return <Badge variant={s.variant}>{s.label}</Badge>;
}
