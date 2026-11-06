/**
 * Copy the engine and its language resources into `api/_vendor/` so the
 * website's Python function (`api/demo.py`) can run the real AutoCorrect
 * engine on Vercel.
 *
 * Runs as part of the install step (see vercel.json). The copy is git-ignored:
 * `src/autocorrect` and `resources/en_base` in the repository root stay the
 * single source of truth, and the function always ships the engine at the same
 * commit as the site.
 */
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const site = resolve(here, "..");
const repo = resolve(site, "..");
const vendor = join(site, "api", "_vendor");

const engineSrc = join(repo, "src", "autocorrect");
const resourcesSrc = join(repo, "resources", "en_base");

if (!existsSync(engineSrc) || !existsSync(resourcesSrc)) {
  console.error(
    `vendor-engine: expected ${engineSrc} and ${resourcesSrc}.\n` +
      "The site must be built from a checkout of the whole repository " +
      "(Vercel: Root Directory = site, with files outside the root included).",
  );
  process.exit(1);
}

const skip = (p) =>
  /(^|[\\/])(__pycache__|\.pytest_cache|\.mypy_cache|tests?)([\\/]|$)/.test(p) || /\.pyc$/.test(p);

rmSync(vendor, { recursive: true, force: true });
mkdirSync(vendor, { recursive: true });
cpSync(engineSrc, join(vendor, "autocorrect"), { recursive: true, filter: (p) => !skip(p) });
cpSync(resourcesSrc, join(vendor, "resources", "en_base"), { recursive: true, filter: (p) => !skip(p) });

function sizeOf(dir) {
  let bytes = 0;
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const st = statSync(p);
    bytes += st.isDirectory() ? sizeOf(p) : st.size;
  }
  return bytes;
}

const bytes = sizeOf(vendor);
writeFileSync(
  join(vendor, "VENDORED.json"),
  JSON.stringify({ vendored_at: new Date().toISOString(), bytes }, null, 2) + "\n",
);
console.log(`vendor-engine: copied engine + resources into api/_vendor (${(bytes / 1048576).toFixed(1)} MB)`);
