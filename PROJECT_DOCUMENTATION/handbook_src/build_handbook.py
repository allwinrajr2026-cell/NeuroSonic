"""Build NeuroSonic_Source_Code_Handbook.pdf from the Markdown parts in this folder.

Needs: Python with `markdown`, `pygments` and `pymupdf` (a scratch environment is fine; the project environments are
not used), and Google Chrome. Steps: Markdown -> one HTML file -> Chrome PDF (pass 1) -> find the page of every
heading -> fill the table of contents -> Chrome PDF (pass 2) -> stamp page numbers and the running footer.

    <python-with-markdown> build_handbook.py
"""
import html
import re
import subprocess
import sys
from pathlib import Path

import markdown
import pymupdf
from pygments.formatters import HtmlFormatter

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "NeuroSonic_Source_Code_Handbook.pdf"
TMP_PDF = HERE / "_pass1.pdf"
HTML_OUT = HERE / "handbook.html"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
TITLE = "NEUROSONIC – SOURCE CODE EXPLANATION & FACULTY VIVA HANDBOOK"
FOOTER = "NeuroSonic – Source Code Explanation & Faculty Viva Handbook"

PARTS = sorted(p for p in HERE.glob("[0-9][0-9]*.md"))

CSS = """
@page { size: A4; margin: 18mm 17mm 20mm 17mm; }
html, body { background: #fff; color: #111; }
body { font-family: "Segoe UI", Calibri, Arial, sans-serif; font-size: 10.4pt; line-height: 1.45; margin: 0;
       -webkit-print-color-adjust: exact; print-color-adjust: exact; }
h1 { break-before: page; font-size: 20pt; color: #0b3d63; border-bottom: 2.5pt solid #0b3d63; padding-bottom: 2mm;
     margin: 0 0 5mm; }
h2 { font-size: 14pt; color: #0b3d63; margin: 7mm 0 2.5mm; break-after: avoid; border-bottom: .6pt solid #9fb6c9;
     padding-bottom: 1mm; }
h2.file { break-before: page; background: #eaf2f8; border: none; border-left: 5pt solid #0b3d63; padding: 2mm 3mm;
          margin-top: 0; }
h3 { font-size: 12pt; color: #12507f; margin: 5mm 0 1.5mm; break-after: avoid; }
h4 { font-size: 10.8pt; color: #12507f; margin: 3.5mm 0 1mm; break-after: avoid; }
p { margin: 0 0 2.2mm; }
ul, ol { margin: .5mm 0 2.5mm; padding-left: 6.5mm; } li { margin: .6mm 0; }
code { font-family: Consolas, "Courier New", monospace; font-size: 8.9pt; background: #f1f3f5; padding: 0 .6mm;
       border-radius: 1mm; }
.codehilite { background: #f7f8fa; border: .5pt solid #ccd3da; border-left: 3pt solid #12507f; padding: 1.8mm 3mm;
              margin: 2mm 0 3mm; break-inside: avoid; border-radius: 1mm; }
.codehilite pre { margin: 0; font-family: Consolas, monospace; font-size: 8.4pt; line-height: 1.32;
                  white-space: pre-wrap; word-break: break-word; }
.codehilite code { background: none; padding: 0; font-size: inherit; }
pre { font-family: Consolas, monospace; font-size: 8.4pt; }
table { border-collapse: collapse; width: 100%; margin: 2mm 0 4mm; font-size: 9.2pt; line-height: 1.3; }
tr { break-inside: avoid; }
th, td { border: .5pt solid #9aa7b3; padding: 1.2mm 1.8mm; vertical-align: top; text-align: left; }
th { background: #dde9f3; }
td code { font-size: 8.3pt; word-break: break-word; }
blockquote { margin: 2.5mm 0 3.5mm; padding: 2mm 4mm; background: #fff8e1; border-left: 4pt solid #e0a800;
             break-inside: avoid; }
blockquote p { margin: 0 0 1mm; }
.cover { text-align: center; padding-top: 38mm; break-after: page; }
.cover h1 { break-before: auto; border: none; font-size: 25pt; line-height: 1.25; margin: 0 0 10mm; }
.cover .sub { font-size: 13pt; color: #333; margin: 2mm 0; }
.cover .box { margin: 22mm auto 0; width: 80%; text-align: left; border: .8pt solid #0b3d63; padding: 4mm 6mm;
              font-size: 10pt; background: #f4f8fb; }
.toc { break-after: page; }
.toc h1 { break-before: auto; }
.toc ul { list-style: none; padding-left: 0; margin: 0; }
.toc li { display: flex; align-items: baseline; margin: .55mm 0; }
.toc li .t { flex: 0 1 auto; } .toc li .dots { flex: 1 1 auto; border-bottom: .8pt dotted #777; margin: 0 1.5mm; }
.toc li .pg { flex: 0 0 auto; font-variant-numeric: tabular-nums; }
.toc li.l1 { font-weight: 700; margin-top: 2.2mm; color: #0b3d63; }
.toc li.l2 { padding-left: 6mm; font-size: 9.6pt; }
.toc a { color: inherit; text-decoration: none; }
a { color: #0b3d63; text-decoration: none; }
.note { font-size: 9pt; color: #444; }
"""


def slug(text, used):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "h"
    base, i = s, 2
    while s in used:
        s, i = f"{base}-{i}", i + 1
    used.add(s)
    return s


def build_html(pages=None):
    md = markdown.Markdown(extensions=["tables", "fenced_code", "codehilite", "attr_list", "md_in_html"],
                           extension_configs={"codehilite": {"guess_lang": False, "css_class": "codehilite"}})
    body = "\n\n".join(p.read_text(encoding="utf-8") for p in PARTS)
    body = md.convert(body)
    used, toc = set(), []

    def head(m):
        lvl, attrs, inner = m.group(1), m.group(2) or "", m.group(3)
        text = html.unescape(re.sub("<[^>]+>", "", inner)).strip()
        if 'class="nontoc"' in attrs:
            return m.group(0)
        hid = slug(text, used)
        toc.append((lvl, hid, text))
        return f'<h{lvl} id="{hid}"{attrs}>{inner}</h{lvl}>'
    body = re.sub(r"<h([12])((?:\s[^>]*)?)>(.*?)</h\1>", head, body, flags=re.S)
    items = []
    for i, (lvl, hid, text) in enumerate(toc):
        pg = "000" if pages is None else str(pages[i])
        items.append(f'<li class="l{lvl}"><a class="t" href="#{hid}">{html.escape(text)}</a>'
                     f'<span class="dots"></span><span class="pg">{pg}</span></li>')
    toc_html = '<section class="toc"><h1 class="nontoc">Table of Contents</h1><ul>' + "".join(items) + "</ul></section>"
    body = body.replace("<p>[[TOC]]</p>", toc_html)
    style = CSS + HtmlFormatter(style="friendly").get_style_defs(".codehilite")
    page = (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(TITLE)}</title>'
            f"<style>{style}</style></head><body>{body}</body></html>")
    HTML_OUT.write_text(page, encoding="utf-8")
    return toc


def print_pdf(target):
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--allow-file-access-from-files", f"--print-to-pdf={target}", HTML_OUT.as_uri()],
                   check=True, capture_output=True, timeout=240)


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def find_pages(pdf, toc):
    doc = pymupdf.open(pdf)
    texts = [norm(p.get_text()) for p in doc]
    # the TOC itself lists every heading: start searching after the last TOC page
    start = max(i for i, t in enumerate(texts) if "table of contents" in t) + 1
    while start < len(texts) and texts[start].count("....") > 3:
        start += 1
    pages, cur = [], start
    for lvl, hid, text in toc:
        key = norm(text)[:45]
        p = cur
        while p < len(texts) and key not in texts[p]:
            p += 1
        if p == len(texts):
            print(f"  ! heading not found: {text!r}")
            p = cur
        pages.append(p + 1)
        cur = p
    n = len(doc)
    doc.close()
    return pages, n


def stamp(src, dst):
    doc = pymupdf.open(src)
    for i, page in enumerate(doc):
        if i == 0:
            continue
        r = page.rect
        page.insert_text((48, r.height - 28), FOOTER, fontsize=7.5, fontname="helv", color=(0.35, 0.35, 0.35))
        label = f"Page {i + 1} of {len(doc)}"
        w = pymupdf.get_text_length(label, fontname="helv", fontsize=8)
        page.insert_text((r.width - 48 - w, r.height - 28), label, fontsize=8, fontname="helv", color=(0.2, 0.2, 0.2))
        page.draw_line((48, r.height - 38), (r.width - 48, r.height - 38), color=(0.7, 0.75, 0.8), width=0.5)
    doc.set_metadata({"title": TITLE, "author": "Allwin Raj", "subject": "NeuroSonic source code explanation"})
    doc.save(dst, garbage=3, deflate=True)
    doc.close()


def main():
    toc = build_html()
    print_pdf(TMP_PDF)
    pages, n1 = find_pages(TMP_PDF, toc)
    build_html(pages)
    print_pdf(TMP_PDF)
    pages2, n2 = find_pages(TMP_PDF, toc)
    if pages2 != pages:
        print("  TOC shifted; one more pass")
        build_html(pages2)
        print_pdf(TMP_PDF)
    stamp(TMP_PDF, OUT)
    TMP_PDF.unlink(missing_ok=True)
    print(f"{OUT}  ({n2} pages, {len(toc)} TOC entries)")


if __name__ == "__main__":
    sys.exit(main())
