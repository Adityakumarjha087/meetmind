"use client";

import { CalendarPlus, Trash, UserPlus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, NativeSelect } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import { isAdmin, useAuth } from "@/lib/auth-context";
import type { IntegrationStatus, Member, Role } from "@/lib/types";

const ROLES: Role[] = ["viewer", "member", "admin", "owner"];
const msg = (err: unknown, fb: string) => (err instanceof ApiError ? err.message : fb);

export default function SettingsPage() {
  const { workspace, user, reloadWorkspaces, selectWorkspace } = useAuth();
  const wsId = workspace!.id;
  const admin = isAdmin(workspace);
  const [members, setMembers] = useState<Member[] | null>(null);
  const [integ, setInteg] = useState<IntegrationStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [invite, setInvite] = useState({ email: "", role: "member" as Role });
  const [name, setName] = useState(workspace!.name);
  const [webhook, setWebhook] = useState("");
  const [autoPost, setAutoPost] = useState(workspace!.slack_auto_post);
  const [newWs, setNewWs] = useState("");

  const load = useCallback(async () => {
    try {
      const [m, i] = await Promise.all([api.members(wsId), api.integrations(wsId)]);
      setMembers(m);
      setInteg(i);
      setError(null);
    } catch (err) {
      setError(msg(err, "Failed to load settings"));
    }
  }, [wsId]);

  useEffect(() => {
    void load();
    setName(workspace!.name);
    setAutoPost(workspace!.slack_auto_post);
  }, [load, workspace]);

  async function saveWorkspace(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.updateWorkspace(wsId, {
        name,
        slack_auto_post: autoPost,
        ...(webhook ? { slack_webhook_url: webhook } : {}),
      });
      setWebhook("");
      await reloadWorkspaces();
      toast.success("Workspace saved");
      void load();
    } catch (err) {
      toast.error(msg(err, "Save failed"));
    }
  }

  async function connectGoogle() {
    try {
      window.location.href = (await api.googleLink()).url;
    } catch (err) {
      toast.error(msg(err, "Google is not configured"));
    }
  }

  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!members || !integ) return <LoadingState />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">Workspace, members and integrations</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Workspace</CardTitle>
            <CardDescription>Your role: {workspace!.role}</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="grid gap-3" onSubmit={saveWorkspace}>
              <div className="grid gap-1.5">
                <Label htmlFor="ws-name">Name</Label>
                <Input id="ws-name" value={name} onChange={(e) => setName(e.target.value)} disabled={!admin} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="slack">Slack incoming webhook</Label>
                <Input
                  id="slack"
                  type="url"
                  placeholder={workspace!.slack_configured ? "Configured — paste a new URL to replace" : "https://hooks.slack.com/services/…"}
                  value={webhook}
                  onChange={(e) => setWebhook(e.target.value)}
                  disabled={!admin}
                />
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={autoPost} onChange={(e) => setAutoPost(e.target.checked)} disabled={!admin} className="size-4" />
                Post summaries to Slack automatically when processing finishes
              </label>
              {admin && <Button type="submit">Save workspace</Button>}
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Integrations & AI backends</CardTitle>
            <CardDescription>Configured on the server via environment variables</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <dl className="grid grid-cols-2 gap-y-2">
              <dt className="text-muted-foreground">LLM provider</dt>
              <dd className="font-medium">{integ.llm_provider}</dd>
              <dt className="text-muted-foreground">Speech-to-text</dt>
              <dd className="font-medium">{integ.stt_backend}</dd>
              <dt className="text-muted-foreground">Diarization</dt>
              <dd className="font-medium">{integ.diarizer_backend}</dd>
              <dt className="text-muted-foreground">Embeddings</dt>
              <dd className="font-medium">{integ.embedding_backend}</dd>
              <dt className="text-muted-foreground">Slack</dt>
              <dd className="font-medium">{integ.slack_configured ? "Connected" : "Not configured"}</dd>
              <dt className="text-muted-foreground">Google Calendar</dt>
              <dd className="font-medium">{integ.google_calendar_connected ? "Connected" : integ.google_oauth_enabled ? "Not connected" : "Disabled on server"}</dd>
            </dl>
            <div className="flex flex-wrap gap-2">
              {integ.google_oauth_enabled && !integ.google_calendar_connected && (
                <Button variant="outline" onClick={connectGoogle}>
                  Connect Google Calendar
                </Button>
              )}
              {integ.google_calendar_connected && (
                <Button
                  variant="outline"
                  onClick={async () => {
                    try {
                      const r = await api.importCalendar(wsId);
                      toast.success(`Imported ${r.imported} upcoming meetings`);
                    } catch (err) {
                      toast.error(msg(err, "Import failed"));
                    }
                  }}
                >
                  <CalendarPlus /> Import upcoming meetings
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Members</CardTitle>
          <CardDescription>Viewers can read; members can upload and edit; admins manage people and integrations.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {admin && (
            <form
              className="flex flex-wrap gap-2"
              onSubmit={async (e) => {
                e.preventDefault();
                try {
                  await api.addMember(wsId, invite.email, invite.role);
                  setInvite({ email: "", role: "member" });
                  toast.success("Member added");
                  void load();
                } catch (err) {
                  toast.error(msg(err, "Could not add member"));
                }
              }}
            >
              <label htmlFor="invite" className="sr-only">
                Email
              </label>
              <Input
                id="invite"
                type="email"
                required
                placeholder="teammate@company.com"
                className="max-w-xs"
                value={invite.email}
                onChange={(e) => setInvite((s) => ({ ...s, email: e.target.value }))}
              />
              <label htmlFor="invite-role" className="sr-only">
                Role
              </label>
              <NativeSelect id="invite-role" value={invite.role} onChange={(e) => setInvite((s) => ({ ...s, role: e.target.value as Role }))}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </NativeSelect>
              <Button type="submit">
                <UserPlus /> Add
              </Button>
            </form>
          )}
          <ul className="divide-y">
            {members.map((m) => (
              <li key={m.user_id} className="flex flex-wrap items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">
                    {m.name} {m.user_id === user?.id && <span className="text-muted-foreground">(you)</span>}
                  </p>
                  <p className="text-xs text-muted-foreground">{m.email}</p>
                </div>
                {admin ? (
                  <>
                    <label htmlFor={`role-${m.user_id}`} className="sr-only">
                      Role for {m.name}
                    </label>
                    <NativeSelect
                      id={`role-${m.user_id}`}
                      value={m.role}
                      onChange={async (e) => {
                        try {
                          await api.updateMember(wsId, m.user_id, e.target.value as Role);
                          void load();
                        } catch (err) {
                          toast.error(msg(err, "Role change failed"));
                        }
                      }}
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </NativeSelect>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove ${m.name}`}
                      onClick={async () => {
                        try {
                          await api.removeMember(wsId, m.user_id);
                          void load();
                        } catch (err) {
                          toast.error(msg(err, "Could not remove"));
                        }
                      }}
                    >
                      <Trash />
                    </Button>
                  </>
                ) : (
                  <span className="text-sm text-muted-foreground">{m.role}</span>
                )}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>New workspace</CardTitle>
          <CardDescription>Separate teams get separate meetings, boards and permissions.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-wrap gap-2"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                const ws = await api.createWorkspace(newWs);
                setNewWs("");
                await reloadWorkspaces();
                selectWorkspace(ws.id);
                toast.success(`Created ${ws.name}`);
              } catch (err) {
                toast.error(msg(err, "Could not create workspace"));
              }
            }}
          >
            <label htmlFor="new-ws" className="sr-only">
              Workspace name
            </label>
            <Input id="new-ws" required placeholder="Workspace name" className="max-w-xs" value={newWs} onChange={(e) => setNewWs(e.target.value)} />
            <Button type="submit" variant="secondary">
              Create
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
