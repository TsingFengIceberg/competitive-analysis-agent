"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { StreamConnection } from "@/components/competition/analysis-session-state";

export type AnalysisStreamEvent =
  | "metadata"
  | "values"
  | "messages-tuple"
  | "progress"
  | "node_end"
  | "end";

interface Props {
  threadId: string | null;
  enabled: boolean;
  onEvent: (event: AnalysisStreamEvent, data: string) => void;
  onConnectionChange?: (connection: StreamConnection, attempt: number) => void;
}

interface Result {
  connection: StreamConnection;
  retry: () => void;
}

const MAX_ATTEMPTS = 5;
const MAX_DELAY_MS = 30_000;

export function useAnalysisStream({
  threadId,
  enabled,
  onEvent,
  onConnectionChange,
}: Props): Result {
  const [retryKey, setRetryKey] = useState(0);
  const [connection, setConnection] = useState<StreamConnection>("inactive");
  const eventRef = useRef(onEvent);
  const connectionRef = useRef(onConnectionChange);

  useEffect(() => {
    eventRef.current = onEvent;
  }, [onEvent]);
  useEffect(() => {
    connectionRef.current = onConnectionChange;
  }, [onConnectionChange]);

  const retry = useCallback(() => setRetryKey((value) => value + 1), []);

  useEffect(() => {
    if (!threadId || !enabled) {
      setConnection("inactive");
      return;
    }

    let destroyed = false;
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let lastEventId: string | null = null;

    const publish = (next: StreamConnection, nextAttempt = attempt) => {
      if (destroyed) return;
      setConnection(next);
      connectionRef.current?.(next, nextAttempt);
    };

    const connect = () => {
      if (destroyed || typeof window === "undefined" || !navigator.onLine) {
        if (!destroyed) publish("offline", attempt);
        return;
      }
      publish(attempt > 0 ? "reconnecting" : "connecting", attempt);
      source?.close();
      const replayQuery = lastEventId
        ? `?last_event_id=${encodeURIComponent(lastEventId)}`
        : "";
      source = new EventSource(`/api/competition/stream/${threadId}${replayQuery}`);

      const events: AnalysisStreamEvent[] = [
        "metadata",
        "values",
        "messages-tuple",
        "progress",
        "node_end",
        "end",
      ];
      for (const event of events) {
        source.addEventListener(event, (message) => {
          const eventMessage = message as MessageEvent<string>;
          // metadata/values use per-connection synthetic IDs on the server;
          // only remember replayable graph event IDs to avoid treating those
          // synthetic IDs as a missing point in the event buffer.
          if (
            event !== "metadata" &&
            event !== "values" &&
            eventMessage.lastEventId
          ) {
            lastEventId = eventMessage.lastEventId;
          }
          eventRef.current(event, eventMessage.data);
          if (event === "metadata") {
            attempt = 0;
            publish("connected", attempt);
          }
          if (event === "end") {
            source?.close();
            source = null;
            publish("inactive", attempt);
          }
        });
      }
      source.addEventListener("open", () => publish("connected", attempt));
      source.addEventListener("error", () => {
        source?.close();
        source = null;
        if (destroyed) return;
        if (!navigator.onLine) {
          publish("offline", attempt);
          return;
        }
        attempt += 1;
        if (attempt > MAX_ATTEMPTS) {
          publish("degraded", attempt);
          return;
        }
        const delay = Math.min(2_000 * 2 ** (attempt - 1), MAX_DELAY_MS);
        publish("reconnecting", attempt);
        timer = setTimeout(connect, delay);
      });
    };

    const handleOffline = () => {
      if (timer) clearTimeout(timer);
      source?.close();
      source = null;
      publish("offline", attempt);
    };
    const handleOnline = () => {
      attempt = 0;
      connect();
    };

    window.addEventListener("offline", handleOffline);
    window.addEventListener("online", handleOnline);
    connect();
    return () => {
      destroyed = true;
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("online", handleOnline);
      if (timer) clearTimeout(timer);
      source?.close();
      source = null;
    };
  }, [enabled, retryKey, threadId]);

  return { connection, retry };
}
