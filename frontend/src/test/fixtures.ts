import type { ActionItem, Insights, Segment, Speaker } from "@/lib/types";

export const speakers: Speaker[] = [
  { id: "s1", label: "SPEAKER_00", display_name: "Speaker 1", talk_time_s: 30, word_count: 90 },
  { id: "s2", label: "SPEAKER_01", display_name: "Speaker 2", talk_time_s: 20, word_count: 50 },
];

export const segments: Segment[] = [
  { id: "a", idx: 0, start_s: 0.5, end_s: 5, text: "Let's plan the launch.", speaker_id: "s1", speaker_name: "Speaker 1", confidence: null },
  { id: "b", idx: 1, start_s: 6, end_s: 10, text: "I will fix the payment bugs.", speaker_id: "s2", speaker_name: "Speaker 2", confidence: null },
];

export function item(overrides: Partial<ActionItem> = {}): ActionItem {
  return {
    id: "i1",
    workspace_id: "w",
    meeting_id: "m1",
    meeting_title: "Q3 Launch Planning",
    title: "Fix the payment bugs",
    description: null,
    owner_name: "Marcus",
    assignee_id: null,
    assignee_name: null,
    due_date: "2026-12-04",
    status: "todo",
    position: 0,
    source_start_s: 19.6,
    created_at: "2026-11-26T00:00:00Z",
    updated_at: "2026-11-26T00:00:00Z",
    ...overrides,
  };
}

export const insights: Insights = {
  executive_summary: "The team planned the Q3 launch.",
  key_points: ["Launch on track"],
  decisions: [{ text: "Launch on September 15.", timestamp_s: 58.7 }],
  action_items: [],
  open_questions: [{ text: "Enough support staff?", timestamp_s: 44.6 }],
  sentiment: [
    { speaker: "Priya", score: 0.6, label: "positive", rationale: null, talk_time_s: 30, word_count: 90 },
    { speaker: "Marcus", score: -0.3, label: "negative", rationale: null, talk_time_s: 20, word_count: 50 },
  ],
  topics: ["launch", "pricing"],
  strategy: "map_reduce",
  chunks_processed: 3,
  engine: "offline",
};
