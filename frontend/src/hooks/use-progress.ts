"use client";

import { useEffect, useRef } from "react";
import { io, type Socket } from "socket.io-client";

import { getAccessToken, onTokenChange } from "@/lib/api";
import { API_URL } from "@/lib/config";
import type { ProgressEvent } from "@/lib/types";

let socket: Socket | null = null;

function getSocket(): Socket {
  if (!socket) {
    socket = io(API_URL, {
      path: "/socket.io",
      transports: ["websocket", "polling"],
      auth: (cb) => cb({ token: getAccessToken() }),
      autoConnect: false,
      reconnectionDelayMax: 5000,
    });
    onTokenChange((token) => {
      if (!token) socket?.disconnect();
    });
  }
  if (!socket.connected && getAccessToken()) socket.connect();
  return socket;
}

/**
 * Subscribe to live pipeline progress for one meeting or a whole workspace.
 * Re-subscribes after reconnects; the caller should still poll as a fallback.
 */
export function useProgress(
  target: { meetingId?: string; workspaceId?: string },
  onEvent: (event: ProgressEvent) => void,
) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const { meetingId, workspaceId } = target;

  useEffect(() => {
    if (!meetingId && !workspaceId) return;
    const s = getSocket();
    const payload = meetingId ? { meeting_id: meetingId } : { workspace_id: workspaceId };
    let room: string | undefined;
    const subscribe = () =>
      s.emit("subscribe", payload, (ack: { ok: boolean; room?: string }) => {
        if (ack?.ok) room = ack.room;
      });
    const listener = (event: ProgressEvent) => {
      if (meetingId ? event.meeting_id === meetingId : event.workspace_id === workspaceId) handler.current(event);
    };
    s.on("connect", subscribe);
    s.on("meeting:progress", listener);
    if (s.connected) subscribe();
    return () => {
      s.off("connect", subscribe);
      s.off("meeting:progress", listener);
      if (room) s.emit("unsubscribe", { room });
    };
  }, [meetingId, workspaceId]);
}
