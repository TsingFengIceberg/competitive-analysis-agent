export type AnalysisLifecycle =
  | "idle"
  | "loading"
  | "submitting"
  | "awaiting_confirmation"
  | "running"
  | "cancelling"
  | "interrupted"
  | "failed"
  | "completed"
  | "approved"
  | "error";

export type StreamConnection =
  | "inactive"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "degraded"
  | "offline";

export type PendingAction = "start" | "confirm" | "cancel" | "rework" | null;

export interface SessionError {
  operation: string;
  message: string;
  retryable: boolean;
}

export interface AnalysisSessionState {
  lifecycle: AnalysisLifecycle;
  stream: StreamConnection;
  streamAttempt: number;
  consecutivePollFailures: number;
  pendingAction: PendingAction;
  lastSuccessfulSyncAt: number | null;
  userError: SessionError | null;
}

export type AnalysisSessionAction =
  | { type: "ROUTE_NEW" }
  | { type: "ROUTE_THREAD_LOADING" }
  | { type: "START_REQUESTED" }
  | { type: "START_RESOLVED"; status: string }
  | { type: "CONFIRM_REQUESTED" }
  | { type: "CANCEL_REQUESTED" }
  | { type: "REWORK_REQUESTED" }
  | { type: "SERVER_SYNCED"; status: string; syncedAt?: number }
  | { type: "POLL_FAILED"; message?: string }
  | { type: "STREAM_CONNECTING"; attempt?: number }
  | { type: "STREAM_CONNECTED" }
  | { type: "STREAM_RETRYING"; attempt: number }
  | { type: "STREAM_DEGRADED"; attempt: number }
  | { type: "BROWSER_OFFLINE" }
  | { type: "BROWSER_ONLINE" }
  | {
      type: "ACTION_FAILED";
      operation: string;
      message: string;
      retryable?: boolean;
    }
  | { type: "CLEAR_ERROR" };

export const INITIAL_ANALYSIS_SESSION: AnalysisSessionState = {
  lifecycle: "idle",
  stream: "inactive",
  streamAttempt: 0,
  consecutivePollFailures: 0,
  pendingAction: null,
  lastSuccessfulSyncAt: null,
  userError: null,
};

const TERMINAL_STATUSES = new Set<AnalysisLifecycle>([
  "idle",
  "interrupted",
  "failed",
  "completed",
  "approved",
  "error",
]);

export function parseAnalysisLifecycle(
  status: string | null | undefined,
): AnalysisLifecycle {
  switch (status) {
    case "idle":
    case "loading":
    case "submitting":
    case "awaiting_confirmation":
    case "running":
    case "cancelling":
    case "interrupted":
    case "failed":
    case "completed":
    case "approved":
    case "error":
      return status;
    default:
      return "error";
  }
}

function lifecycleFromServer(
  current: AnalysisSessionState,
  status: string,
): AnalysisSessionState {
  const lifecycle = parseAnalysisLifecycle(status);
  return {
    ...current,
    lifecycle,
    pendingAction: null,
    stream: TERMINAL_STATUSES.has(lifecycle) ? "inactive" : current.stream,
    userError:
      lifecycle === "error"
        ? {
            operation: "sync",
            message: "服务器返回了无法识别的分析状态。",
            retryable: false,
          }
        : null,
  };
}

export function analysisSessionReducer(
  state: AnalysisSessionState,
  action: AnalysisSessionAction,
): AnalysisSessionState {
  switch (action.type) {
    case "ROUTE_NEW":
      return { ...INITIAL_ANALYSIS_SESSION };
    case "ROUTE_THREAD_LOADING":
      return { ...INITIAL_ANALYSIS_SESSION, lifecycle: "loading" };
    case "START_REQUESTED":
      return {
        ...state,
        lifecycle: "submitting",
        pendingAction: "start",
        userError: null,
      };
    case "START_RESOLVED":
      return lifecycleFromServer(
        { ...state, stream: "inactive" },
        action.status,
      );
    case "CONFIRM_REQUESTED":
      return { ...state, pendingAction: "confirm", userError: null };
    case "CANCEL_REQUESTED":
      return {
        ...state,
        lifecycle: "cancelling",
        pendingAction: "cancel",
        userError: null,
      };
    case "REWORK_REQUESTED":
      return {
        ...state,
        lifecycle: "running",
        pendingAction: "rework",
        stream: "connecting",
        userError: null,
      };
    case "SERVER_SYNCED":
      return {
        ...lifecycleFromServer(state, action.status),
        consecutivePollFailures: 0,
        lastSuccessfulSyncAt: action.syncedAt ?? Date.now(),
      };
    case "POLL_FAILED":
      return {
        ...state,
        consecutivePollFailures: state.consecutivePollFailures + 1,
        userError:
          state.consecutivePollFailures + 1 >= 2
            ? {
                operation: "sync",
                message: action.message ?? "暂时无法同步分析状态。",
                retryable: true,
              }
            : state.userError,
      };
    case "STREAM_CONNECTING":
      return {
        ...state,
        stream:
          action.attempt && action.attempt > 0 ? "reconnecting" : "connecting",
        streamAttempt: action.attempt ?? state.streamAttempt,
      };
    case "STREAM_CONNECTED":
      return {
        ...state,
        stream: "connected",
        streamAttempt: 0,
        userError:
          state.userError?.operation === "stream" ? null : state.userError,
      };
    case "STREAM_RETRYING":
      return {
        ...state,
        stream: "reconnecting",
        streamAttempt: action.attempt,
      };
    case "STREAM_DEGRADED":
      return {
        ...state,
        stream: "degraded",
        streamAttempt: action.attempt,
        userError: {
          operation: "stream",
          message: "实时更新暂时断开，页面会继续同步分析状态。",
          retryable: true,
        },
      };
    case "BROWSER_OFFLINE":
      return {
        ...state,
        stream: "offline",
        userError: {
          operation: "network",
          message: "网络连接已断开，恢复后会自动重试。",
          retryable: true,
        },
      };
    case "BROWSER_ONLINE":
      return {
        ...state,
        stream: state.lifecycle === "running" ? "reconnecting" : state.stream,
        userError: null,
      };
    case "ACTION_FAILED":
      return {
        ...state,
        pendingAction: null,
        userError: {
          operation: action.operation,
          message: action.message,
          retryable: action.retryable ?? true,
        },
      };
    case "CLEAR_ERROR":
      return { ...state, userError: null };
    default:
      return state;
  }
}

export function canSubmitAnalysis(state: AnalysisSessionState): boolean {
  return (
    state.pendingAction === null &&
    [
      "idle",
      "completed",
      "approved",
      "interrupted",
      "failed",
      "error",
    ].includes(state.lifecycle)
  );
}

export function canStopAnalysis(state: AnalysisSessionState): boolean {
  return (
    state.pendingAction === null &&
    (state.lifecycle === "running" || state.lifecycle === "submitting")
  );
}
