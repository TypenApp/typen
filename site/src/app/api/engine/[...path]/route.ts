import { NextRequest, NextResponse } from "next/server";

/**
 * Proxy for the live demo.
 *
 * The site never simulates corrections. Every keystroke in the demo is sent
 * to the real Python engine (`autocorrect-sandbox --no-browser`, the same
 * `InputSessionManager` + `AutocorrectEngine` the desktop daemon runs) via
 * this route, so what visitors see is exactly what the product does.
 *
 * Engine location: AUTOCORRECT_ENGINE_URL (default http://127.0.0.1:8765).
 * When the engine is unreachable we answer 503 and the UI says so instead
 * of faking output.
 */

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const ENGINE_URL = (process.env.AUTOCORRECT_ENGINE_URL ?? "http://127.0.0.1:8765").replace(/\/$/, "");
const ALLOWED = new Set([
  "api/health",
  "api/key",
  "api/reset",
  "api/caret",
  "api/dictionary",
  "api/dictionary/add",
  "api/dictionary/delete",
  "api/dictionary/dismiss",
]);
const SESSION_RE = /^[A-Za-z0-9_-]{8,64}$/;
const TIMEOUT_MS = 4000;

async function forward(req: NextRequest, segments: string[]): Promise<NextResponse> {
  const path = segments.join("/");
  if (!ALLOWED.has(path)) {
    return NextResponse.json({ ok: false, error: "unknown engine route" }, { status: 404 });
  }

  const session = req.headers.get("x-session-id") ?? "";
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (SESSION_RE.test(session)) headers["X-Session-Id"] = session;

  let body: string | undefined;
  if (req.method === "POST") {
    body = await req.text();
    if (body.length > 4096) {
      return NextResponse.json({ ok: false, error: "payload too large" }, { status: 413 });
    }
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const upstream = await fetch(`${ENGINE_URL}/${path}`, {
      method: req.method,
      headers,
      body,
      cache: "no-store",
      signal: controller.signal,
    });
    const text = await upstream.text();
    return new NextResponse(text, {
      status: upstream.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { ok: false, offline: true, error: "engine unreachable" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  } finally {
    clearTimeout(timer);
  }
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return forward(req, path);
}

export async function POST(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return forward(req, path);
}
