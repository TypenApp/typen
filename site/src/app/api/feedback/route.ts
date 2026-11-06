import { NextResponse } from "next/server";
import { GITHUB_REPO } from "@/data/releases";

/**
 * POST /api/feedback
 *
 * One endpoint for both the website form and the desktop app:
 *   kind = "suggestion"  -> a GitHub Discussion (category: Ideas by default)
 *   kind = "bug"         -> a GitHub Issue labelled `bug` + `source:<site|desktop>`
 *
 * Environment (Vercel project settings):
 *   GITHUB_FEEDBACK_TOKEN                fine-grained PAT with Issues: write and
 *                                        Discussions: write on the target repo (required)
 *   GITHUB_FEEDBACK_REPO                 owner/name  (default: TypenApp/typen)
 *   GITHUB_FEEDBACK_DISCUSSION_CATEGORY  discussion category name (default: Ideas)
 *
 * Nothing is stored here. The alias and optional email are written into the
 * GitHub post body; the email is only ever shown as a "reply to" line.
 */

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Kind = "suggestion" | "bug";
type Source = "site" | "desktop";

interface FeedbackBody {
  kind?: unknown;
  alias?: unknown;
  email?: unknown;
  note?: unknown;
  steps?: unknown;
  source?: unknown;
  app_version?: unknown;
  diagnostics?: unknown;
  website?: unknown; // honeypot: must be empty
}

const MAX_NOTE = 4000;
const MAX_STEPS = 2000;
const MAX_ALIAS = 60;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

// ---------------------------------------------------------------- rate limit
// Best effort, per-instance: enough to stop a stuck client or a casual script.
const WINDOW_MS = 10 * 60 * 1000;
const MAX_PER_WINDOW = 6;
const hits = new Map<string, number[]>();

function rateLimited(key: string): boolean {
  const now = Date.now();
  const recent = (hits.get(key) ?? []).filter((t) => now - t < WINDOW_MS);
  if (recent.length >= MAX_PER_WINDOW) {
    hits.set(key, recent);
    return true;
  }
  recent.push(now);
  hits.set(key, recent);
  if (hits.size > 5000) hits.clear();
  return false;
}

// ---------------------------------------------------------------- helpers
const str = (v: unknown, max: number): string =>
  typeof v === "string" ? v.replace(/\r\n?/g, "\n").trim().slice(0, max) : "";

function json(status: number, body: Record<string, unknown>) {
  return NextResponse.json(body, { status });
}

function clientKey(req: Request): string {
  const fwd = req.headers.get("x-forwarded-for") ?? "";
  return fwd.split(",")[0].trim() || req.headers.get("x-real-ip") || "anon";
}

function fence(text: string): string {
  // Never let user text break out of the code block.
  const safe = text.replace(/```/g, "'''");
  return "```\n" + safe + "\n```";
}

function diagnosticsTable(diag: unknown): string {
  if (!diag || typeof diag !== "object") return "";
  const rows = Object.entries(diag as Record<string, unknown>)
    .filter(([, v]) => v !== "" && v !== null && v !== undefined)
    .slice(0, 24)
    .map(([k, v]) => `| ${k.replace(/\|/g, " ")} | ${String(v).replace(/\|/g, " ").slice(0, 120)} |`);
  if (rows.length === 0) return "";
  return ["| Diagnostic | Value |", "| --- | --- |", ...rows].join("\n");
}

async function gh<T>(token: string, url: string, init: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "typen-site-feedback",
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
    cache: "no-store",
  });
  const text = await res.text();
  let data: unknown = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const msg = (data as { message?: string }).message ?? `GitHub HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data as T;
}

async function graphql<T>(token: string, query: string, variables: Record<string, unknown>): Promise<T> {
  const data = await gh<{ data?: T; errors?: { message: string }[] }>(token, "https://api.github.com/graphql", {
    method: "POST",
    body: JSON.stringify({ query, variables }),
  });
  if (data.errors?.length) throw new Error(data.errors.map((e) => e.message).join("; "));
  if (!data.data) throw new Error("GitHub returned no data");
  return data.data;
}

// ---------------------------------------------------------------- GitHub writes
async function createIssue(
  token: string,
  repo: string,
  title: string,
  body: string,
  labels: string[],
): Promise<string> {
  const created = await gh<{ html_url: string }>(token, `https://api.github.com/repos/${repo}/issues`, {
    method: "POST",
    body: JSON.stringify({ title, body, labels }),
  });
  return created.html_url;
}

async function createDiscussion(
  token: string,
  repo: string,
  categoryName: string,
  title: string,
  body: string,
): Promise<string> {
  const [owner, name] = repo.split("/");
  const lookup = await graphql<{
    repository: { id: string; discussionCategories: { nodes: { id: string; name: string }[] } };
  }>(
    token,
    `query($owner:String!,$name:String!){
       repository(owner:$owner,name:$name){
         id
         discussionCategories(first:25){ nodes{ id name } }
       }
     }`,
    { owner, name },
  );
  const cats = lookup.repository.discussionCategories.nodes;
  const category =
    cats.find((c) => c.name.toLowerCase() === categoryName.toLowerCase()) ??
    cats.find((c) => /idea/i.test(c.name)) ??
    cats.find((c) => /general/i.test(c.name)) ??
    cats[0];
  if (!category) throw new Error("The repository has no discussion categories (are Discussions enabled?)");

  const created = await graphql<{ createDiscussion: { discussion: { url: string } } }>(
    token,
    `mutation($repo:ID!,$cat:ID!,$title:String!,$body:String!){
       createDiscussion(input:{repositoryId:$repo,categoryId:$cat,title:$title,body:$body}){
         discussion{ url }
       }
     }`,
    { repo: lookup.repository.id, cat: category.id, title, body },
  );
  return created.createDiscussion.discussion.url;
}

// ---------------------------------------------------------------- handler
export async function POST(req: Request) {
  let body: FeedbackBody;
  try {
    body = (await req.json()) as FeedbackBody;
  } catch {
    return json(400, { ok: false, error: "Send JSON." });
  }

  // Honeypot: bots fill every field.
  if (str(body.website, 10) !== "") return json(200, { ok: true, url: "" });

  const kind = body.kind === "bug" ? "bug" : body.kind === "suggestion" ? "suggestion" : null;
  const alias = str(body.alias, MAX_ALIAS);
  const email = str(body.email, 120);
  const note = str(body.note, MAX_NOTE);
  const steps = str(body.steps, MAX_STEPS);
  const source: Source = body.source === "desktop" ? "desktop" : "site";
  const appVersion = str(body.app_version, 40);

  if (!kind) return json(400, { ok: false, error: "Choose Suggestion or Report a bug." });
  if (!alias) return json(400, { ok: false, error: "Please add an alias." });
  if (email && !EMAIL_RE.test(email)) return json(400, { ok: false, error: "That email address does not look right." });
  if (note.length < 10) return json(400, { ok: false, error: "Tell us a little more (at least 10 characters)." });

  if (rateLimited(clientKey(req))) {
    return json(429, { ok: false, error: "Too many reports from this address. Please try again in a few minutes." });
  }

  const token = process.env.GITHUB_FEEDBACK_TOKEN;
  const repo = process.env.GITHUB_FEEDBACK_REPO || GITHUB_REPO;
  const category = process.env.GITHUB_FEEDBACK_DISCUSSION_CATEGORY || "Ideas";
  if (!token) {
    return json(503, { ok: false, error: "Feedback is not configured on the server yet. Please open an issue on GitHub instead." });
  }

  const firstLine = note.split("\n")[0].replace(/\s+/g, " ").trim();
  const title = (firstLine.length > 72 ? firstLine.slice(0, 69) + "…" : firstLine) || (kind === "bug" ? "Bug report" : "Suggestion");

  const meta: string[] = [`**From:** ${alias}${email ? ` · reply to: ${email}` : ""}`, `**Via:** ${source}${appVersion ? ` · Typen ${appVersion}` : ""}`];
  const parts: string[] = [meta.join("  \n"), "", kind === "bug" ? "### What happened" : "### Suggestion", "", fence(note)];
  if (kind === "bug" && steps) parts.push("", "### Steps to reproduce", "", fence(steps));
  const diag = kind === "bug" ? diagnosticsTable(body.diagnostics) : "";
  if (diag) parts.push("", "### Diagnostics", "", diag);
  parts.push("", "---", `_Submitted through the Typen ${source === "desktop" ? "desktop app" : "website"} feedback form._`);
  const markdown = parts.join("\n");

  try {
    const url =
      kind === "bug"
        ? await createIssue(token, repo, title, markdown, ["bug", `source:${source}`])
        : await createDiscussion(token, repo, category, title, markdown);
    return json(200, { ok: true, url });
  } catch (err) {
    const message = err instanceof Error ? err.message : "GitHub rejected the request";
    console.error("[feedback]", kind, message);
    return json(502, { ok: false, error: `GitHub rejected the request: ${message}` });
  }
}

export async function GET() {
  return json(405, { ok: false, error: "POST a feedback payload." });
}
