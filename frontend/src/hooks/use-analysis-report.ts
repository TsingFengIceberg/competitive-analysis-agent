"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface AnalysisReportPollResult {
  status: string;
  [key: string]: unknown;
}

interface Props {
  threadId: string | null;
  enabled: boolean;
  poll: (
    threadId: string,
    signal: AbortSignal,
  ) => Promise<AnalysisReportPollResult>;
  onSuccess: (report: AnalysisReportPollResult) => void;
  onError: (error: unknown, consecutiveFailures: number) => void;
  shouldContinue?: (report: AnalysisReportPollResult) => boolean;
  intervalMs?: number;
}

interface Result {
  retry: () => void;
  consecutiveFailures: number;
  polling: boolean;
}

export function useAnalysisReport({
  threadId,
  enabled,
  poll,
  onSuccess,
  onError,
  shouldContinue = () => true,
  intervalMs = 3_000,
}: Props): Result {
  const [retryKey, setRetryKey] = useState(0);
  const [consecutiveFailures, setConsecutiveFailures] = useState(0);
  const [polling, setPolling] = useState(false);
  const pollRef = useRef(poll);
  const successRef = useRef(onSuccess);
  const errorRef = useRef(onError);
  const continueRef = useRef(shouldContinue);

  useEffect(() => {
    pollRef.current = poll;
  }, [poll]);
  useEffect(() => {
    successRef.current = onSuccess;
  }, [onSuccess]);
  useEffect(() => {
    errorRef.current = onError;
  }, [onError]);
  useEffect(() => {
    continueRef.current = shouldContinue;
  }, [shouldContinue]);

  const retry = useCallback(() => setRetryKey((value) => value + 1), []);

  useEffect(() => {
    if (!threadId || !enabled) {
      setPolling(false);
      setConsecutiveFailures(0);
      return;
    }

    let destroyed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null;
    let failures = 0;

    const schedule = (delay: number) => {
      if (!destroyed) timer = setTimeout(run, delay);
    };

    const run = async () => {
      if (destroyed) return;
      controller?.abort();
      controller = new AbortController();
      setPolling(true);
      try {
        const report = await pollRef.current(threadId, controller.signal);
        if (destroyed) return;
        failures = 0;
        setConsecutiveFailures(0);
        successRef.current(report);
        if (continueRef.current(report)) schedule(intervalMs);
      } catch (error) {
        if (
          destroyed ||
          (error instanceof DOMException && error.name === "AbortError")
        )
          return;
        failures += 1;
        setConsecutiveFailures(failures);
        errorRef.current(error, failures);
        schedule(intervalMs);
      } finally {
        if (!destroyed) setPolling(false);
      }
    };

    void run();
    return () => {
      destroyed = true;
      if (timer) clearTimeout(timer);
      controller?.abort();
      setPolling(false);
    };
  }, [enabled, intervalMs, retryKey, threadId]);

  return { retry, consecutiveFailures, polling };
}
