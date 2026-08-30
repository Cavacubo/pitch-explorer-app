#!/usr/bin/env python3
"""Render every Markdown file in this folder to a self-contained *_preview.html.

Each preview is a single static HTML file (inline CSS, no external assets) that opens
in a browser and renders the Markdown, including tables, code, and headings. Re-run after
editing any .md.  Usage:  python make_previews.py
"""

import glob, html, os, re
import markdown

HERE = os.path.dirname(os.path.abspath(__file__))

CSS = """
:root{color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:#f6f7f9;color:#1f2328;
     font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:32px 24px 80px}
.doc{background:#fff;border:1px solid #e3e5ea;border-radius:12px;padding:40px 44px;
     box-shadow:0 1px 3px rgba(20,20,50,.05)}
.crumb{color:#6b7280;font-size:12.5px;margin:0 0 18px;letter-spacing:.02em}
h1,h2,h3,h4{line-height:1.25;font-weight:700;margin:1.6em 0 .5em}
h1{font-size:1.9em;margin-top:0;border-bottom:1px solid #eceef1;padding-bottom:.3em}
h2{font-size:1.4em;border-bottom:1px solid #eceef1;padding-bottom:.25em}
h3{font-size:1.15em}
p,ul,ol{margin:.6em 0}
a{color:#3159d8;text-decoration:none}a:hover{text-decoration:underline}
code{background:#f0f1f4;padding:.15em .4em;border-radius:5px;font-size:.87em;
     font-family:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace}
pre{background:#0f1020;color:#e7e7f2;padding:14px 16px;border-radius:9px;overflow:auto;font-size:13px}
pre code{background:none;padding:0;color:inherit}
blockquote{margin:.8em 0;padding:.2em 1em;border-left:4px solid #c7ccd6;color:#4b5563;background:#fafbfc}
table{border-collapse:collapse;width:100%;margin:1em 0;font-size:14px;display:block;overflow-x:auto}
th,td{border:1px solid #dfe2e7;padding:8px 11px;text-align:left;vertical-align:top}
th{background:#f3f4f7;font-weight:600}
tr:nth-child(even) td{background:#fafbfc}
hr{border:0;border-top:1px solid #e3e5ea;margin:2em 0}
img{max-width:100%;height:auto}
strong{font-weight:700}
.doc>*:first-child{margin-top:0}
"""

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>{css}</style></head>
<body><div class="wrap"><div class="doc">
<div class="crumb">pitch_explorer / {name} &nbsp;·&nbsp; rendered preview (do not edit; edit the .md)</div>
{body}
</div></div></body></html>
"""


def title_of(md_text, fallback):
    m = re.search(r"^#\s+(.+)$", md_text, re.M)
    return m.group(1).strip() if m else fallback


def main():
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists", "attr_list"]
    )
    files = sorted(f for f in glob.glob(os.path.join(HERE, "*.md")))
    if not files:
        print("No .md files found.")
        return
    for path in files:
        name = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        md.reset()
        body = md.convert(text)
        out = os.path.splitext(path)[0] + "_preview.html"
        with open(out, "w", encoding="utf-8") as f:
            f.write(
                TEMPLATE.format(
                    title=html.escape(title_of(text, name)),
                    css=CSS,
                    name=html.escape(name),
                    body=body,
                )
            )
        print(f"  {name:22s} -> {os.path.basename(out)}")
    print(f"Rendered {len(files)} preview(s).")


if __name__ == "__main__":
    main()
