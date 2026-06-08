import { type NextRequest } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ thread_id: string }> },
) {
  const { thread_id } = await params;
  const backend = "http://127.0.0.1:8001";
  const url = `${backend}/api/competition/stream/${thread_id}`;

  const lastEventId = request.headers.get("Last-Event-ID");

  // Use Node.js http for true streaming (no buffering)
  const http = await import("node:http");

  const stream = new ReadableStream({
    start(controller) {
      const req = http.get(url, {
        headers: lastEventId ? { "Last-Event-ID": lastEventId } : {},
      }, (res) => {
        res.on("data", (chunk: Buffer) => {
          controller.enqueue(new Uint8Array(chunk));
        });
        res.on("end", () => {
          controller.close();
        });
        res.on("error", (err: Error) => {
          controller.error(err);
        });
      });
      req.on("error", (err: Error) => {
        controller.error(err);
      });

      // Cleanup if client disconnects
      request.signal.addEventListener("abort", () => {
        req.destroy();
        try { controller.close(); } catch { /* already closed */ }
      });
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
