import { NextResponse } from "next/server";
import manifest from "@/data/release-manifest.json";

/** Public discovery document for in-app updates (and the download page). */
export async function GET() {
  return NextResponse.json(manifest, {
    headers: {
      "Cache-Control": "public, max-age=300, stale-while-revalidate=600",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
