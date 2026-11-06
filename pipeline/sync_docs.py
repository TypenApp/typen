"""
Synchronise the canonical documentation articles in `site/src/data/docs.ts`
into standalone Markdown files in `docs/` (for the `TypenApp/docs` repository).

Usage:
    python -m pipeline.sync_docs [--out docs] [--check]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DOCS_TS_PATH = ROOT / "site" / "src" / "data" / "docs.ts"
DEFAULT_OUT_DIR = ROOT / "docs"


def _extract_articles_from_ts(ts_source: str) -> list[dict[str, Any]]:
    """
    Parse the `DOC_ARTICLES` array literal from `site/src/data/docs.ts` without
    requiring a Node.js runtime.
    """
    marker = "export const DOC_ARTICLES: DocArticle[] = "
    idx = ts_source.find(marker)
    if idx < 0:
        raise ValueError("Could not locate DOC_ARTICLES in site/src/data/docs.ts")

    start = idx + len(marker)
    end_marker = "\nexport function getDocBySlug"
    end = ts_source.find(end_marker, start)
    if end < 0:
        end = len(ts_source)
    raw_array = ts_source[start:end].strip().rstrip(";")

    # Convert TypeScript object literal syntax to valid JSON:
    # 1. Replace `code: \`...\`` template literals with JSON string literals
    def _replace_code_backticks(m: re.Match[str]) -> str:
        prefix = m.group(1)
        inner = m.group(2).replace("\\\\", "\\").replace("\\n", "\n")
        return f"{prefix}{json.dumps(inner)}"

    json_like = re.sub(r"(code\s*:\s*)`([^`]*)`", _replace_code_backticks, raw_array)
    # 2. Quote unquoted identifier keys at the start of object properties
    out_lines: list[str] = []
    for line in json_like.splitlines():
        m = re.match(
            r"^(\s*)(slug|title|shortTitle|category|summary|readingTime|sections|id|heading|paragraphs|bullets|codeBlock|language|code)\s*:(.*)$",
            line,
        )
        if m:
            out_lines.append(f'{m.group(1)}"{m.group(2)}":{m.group(3)}')
        else:
            out_lines.append(line)
    json_like = "\n".join(out_lines)
    # 3. Remove trailing commas before `]` or `}`
    json_like = re.sub(r",(\s*[\]\}])", r"\1", json_like)
    return list(json.loads(json_like))


def render_article_markdown(article: dict[str, Any]) -> str:
    """Render a single `DocArticle` dictionary into a clean Markdown document."""
    lines: list[str] = [
        f"# {article['title']}",
        "",
        f"> **{article['category']}** · {article['readingTime']}  ",
        f"> {article['summary']}",
        "",
        "## Contents",
        "",
    ]
    for idx, sec in enumerate(article["sections"], start=1):
        lines.append(f"{idx}. [{sec['heading']}](#{sec['id']})")
    lines.append("")
    lines.append("---")
    lines.append("")

    for sec in article["sections"]:
        lines.append(f'<a id="{sec["id"]}"></a>')
        lines.append(f"## {sec['heading']}")
        lines.append("")
        for para in sec.get("paragraphs", []):
            lines.append(para)
            lines.append("")
        for bullet in sec.get("bullets", []):
            lines.append(f"- {bullet}")
        if sec.get("bullets"):
            lines.append("")
        code_block = sec.get("codeBlock")
        if code_block:
            lines.append(f"**{code_block['title']}**")
            lines.append("")
            lines.append(f"```{code_block['language']}")
            lines.append(code_block["code"].rstrip())
            lines.append("```")
            lines.append("")

    lines.extend(
        [
            "---",
            "",
            "*Part of the [Typen Documentation](https://github.com/TypenApp/docs) · "
            "[Read on the web](https://autocorrect-desktop.vercel.app/docs/"
            f"{article['slug']}) · "
            "[TypenApp on GitHub](https://github.com/TypenApp)*",
            "",
        ]
    )
    return "\n".join(lines)


def render_index_markdown(articles: list[dict[str, Any]]) -> str:
    """Render `README.md` for `TypenApp/docs`."""
    lines: list[str] = [
        "# Typen Documentation (`TypenApp/docs`)",
        "",
        "Official documentation, architecture specifications, security guarantees, and CLI reference for **Typen** — the free, open-source, offline-first system-wide autocorrect and writing assistant for Windows, macOS, and Linux.",
        "",
        "- **Website & Live Demo**: <https://autocorrect-desktop.vercel.app>",
        "- **Web Docs**: <https://autocorrect-desktop.vercel.app/docs>",
        "- **GitHub Organisation**: <https://github.com/TypenApp>",
        "",
        "## Guides & Reference",
        "",
        "| # | Category | Guide | Summary |",
        "| --- | --- | --- | --- |",
    ]
    for idx, art in enumerate(articles, start=1):
        num = f"{idx:02d}"
        link = f"[{art['title']}]({art['slug']}.md)"
        lines.append(f"| `{num}` | {art['category']} | {link} | {art['summary']} |")

    lines.extend(
        [
            "",
            "## Official `TypenApp` Repositories",
            "",
            "| Repository | Role |",
            "| --- | --- |",
            "| [`TypenApp/typen`](https://github.com/TypenApp/typen) | Main desktop application, OS keyboard hooks, Settings UI, packaging and website |",
            "| [`TypenApp/language-data`](https://github.com/TypenApp/language-data) | Global English lexicon pipeline, confusion sets, domain packs and held-out corpus |",
            "| [`TypenApp/model-resources`](https://github.com/TypenApp/model-resources) | Optional Layer 2 local ONNX/GGUF grammar and rewrite model descriptors and signing |",
            "| [`TypenApp/docs`](https://github.com/TypenApp/docs) | Product documentation, architecture guides and CLI reference |",
            "",
            "## Contributing to the Docs",
            "",
            "Pull requests fixing typos, clarifying OS setup steps, or expanding technical sections are always welcome! Each `.md` file in this repository corresponds 1-to-1 with an article on `/docs/<slug>`.",
            "",
            "## Licence",
            "",
            "MIT. See [`LICENSE`](LICENSE).",
            "",
        ]
    )
    return "\n".join(lines)


def sync_docs(out_dir: Path = DEFAULT_OUT_DIR, *, check: bool = False) -> dict[str, str]:
    ts_source = DOCS_TS_PATH.read_text(encoding="utf-8")
    articles = _extract_articles_from_ts(ts_source)

    expected_files: dict[str, str] = {
        "README.md": render_index_markdown(articles),
    }
    for art in articles:
        expected_files[f"{art['slug']}.md"] = render_article_markdown(art)

    if check:
        stale: list[str] = []
        for rel_name, content in expected_files.items():
            target = out_dir / rel_name
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                stale.append(rel_name)
        if stale:
            raise SystemExit(
                f"Documentation files in {out_dir} are out of sync ({', '.join(stale)}); "
                "run `python -m pipeline.sync_docs`"
            )
        return expected_files

    out_dir.mkdir(parents=True, exist_ok=True)
    for rel_name, content in expected_files.items():
        (out_dir / rel_name).write_text(content, encoding="utf-8")
    return expected_files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT_DIR, help="Output directory for Markdown docs"
    )
    parser.add_argument("--check", action="store_true", help="Verify that output files match docs.ts")
    args = parser.parse_args(argv)

    written = sync_docs(args.out, check=args.check)
    action = "Verified" if args.check else "Synced"
    print(f"{action} {len(written)} documentation files in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
