"""Build the assignment PDFs from HTML fragments in sections/.

  python build.py            -> all documents
  python build.py DA1 Lab10  -> only those

Fragments use [[key]] / [[k1,k2]] citations (refs.py), <figure id="f-..."> / <table id="t-..."> with {{f-...}} /
{{t-...}} cross-references. Numbering is per document. PDFs are printed with headless Chrome and their pages counted.
"""
import html
import re
import subprocess
import sys
from pathlib import Path

from docs import DEMO_LINE, DOCS
from refs import REFS

HERE = Path(__file__).resolve().parent
OUTDIR = HERE.parent
SECTIONS = HERE / "sections"
HTMLDIR = HERE / "html"
HTMLDIR.mkdir(exist_ok=True)
IMPL = HERE.parents[1]
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PAGES = {}
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII",
         "XVIII", "XIX", "XX", "XXI", "XXII", "XXIII", "XXIV", "XXV"]


def img_paths(s):
    # fragments write src="fig:NAME" (assignment figure), "pub:NAME" (publication figure) or "shot:NAME"
    s = s.replace('src="fig:', f'src="{(HERE / "figures").as_uri()}/')
    s = s.replace('src="pub:', f'src="{(IMPL / "publication" / "figures").as_uri()}/')
    return s.replace('src="shot:', f'src="{(IMPL / "docs" / "images").as_uri()}/')


def number(body, style):
    roman = style == "ieee"
    # figures
    fig_ids = re.findall(r'<figure[^>]*id="(f-[\w-]+)"', body)
    figmap = {fid: i + 1 for i, fid in enumerate(fig_ids)}
    for fid, n in figmap.items():
        body = re.sub(rf'(<figure[^>]*id="{fid}"[^>]*>.*?<figcaption>)', rf"\1<b>Fig. {n}.</b> ", body, count=1, flags=re.S)
    # tables
    tab_ids = re.findall(r'<table[^>]*id="(t-[\w-]+)"', body)
    tabmap = {tid: i + 1 for i, tid in enumerate(tab_ids)}
    for tid, n in tabmap.items():
        label = f"TABLE {ROMAN[n - 1]}" if roman else f"Table {n}."
        body = re.sub(rf'(<table[^>]*id="{tid}"[^>]*>\s*<caption>)', rf'\1<span class="tl">{label}</span><br>' if roman
                      else rf'\1<b>{label}</b> ', body, count=1)

    def xref(m):
        k = m.group(1)
        if k in figmap:
            return f"Fig. {figmap[k]}"
        if k in tabmap:
            return f"Table {ROMAN[tabmap[k] - 1] if roman else tabmap[k]}"
        raise KeyError(f"unknown cross-reference {k}")
    body = re.sub(r"\{\{([ft]-[\w-]+)\}\}", xref, body)
    # citations
    order = []

    def cite(m):
        keys = [k.strip() for k in m.group(1).split(",")]
        nums = []
        for k in keys:
            if k not in REFS:
                raise KeyError(f"unknown reference {k}")
            if k not in order:
                order.append(k)
            nums.append(order.index(k) + 1)
        return ", ".join(f"[{n}]" for n in nums)
    body = re.sub(r"\[\[([\w,\s]+)\]\]", cite, body)
    refs = "\n".join(f'<li>{REFS[k]}</li>' for k in order)
    return body, refs, len(figmap), len(tabmap)


def build(key, spec):
    style = spec["style"]
    parts = [img_paths((SECTIONS / f"{s}.html").read_text(encoding="utf-8")) for s in spec["sections"]]
    body = "\n".join(parts)
    for k, n in PAGES.items():
        body = body.replace("{{pages:%s}}" % k, str(n))
    for old, new in spec.get("subs", []):  # wording for combined documents (e.g. "Review 2" -> section name)
        body = body.replace(old, new)
    body, refs, nf, nt = number(body, style)
    css = (HERE / ("report.css" if style == "form" else f"{style}.css")).read_text(encoding="utf-8")
    if style == "form":
        css += (HERE / "form.css").read_text(encoding="utf-8")
    front = img_paths(spec.get("front", ""))
    if style == "ieee":
        doc = f"""<div class="cols"><header class="title-block"><h1>{spec['title']}</h1>{spec['authors']}<div class="note-top demo">{DEMO_LINE}</div></header>
{spec.get('abstract', '')}{body}
{'<h2 class="norule">References</h2><ol class="refs">' + refs + '</ol>' if refs else ''}</div>"""
    else:
        toc = ""
        if spec.get("toc"):
            items = []
            ch = sub = 0
            for lvl, attrs, txt in re.findall(r"<h([23])([^>]*)>(.*?)</h\1>", body, flags=re.S):
                t = re.sub("<[^>]+>", "", txt)
                if "unnum" not in attrs:
                    if lvl == "2":
                        ch, sub = ch + 1, 0
                        t = f"{ch}. {t}"
                    elif ch:
                        sub += 1
                        t = f"{ch}.{sub} {t}"
                items.append(f'<li class="toc{lvl}">{t}</li>')
            toc = '<section class="toc"><h2 class="unnum">Table of Contents</h2><ul>' + "".join(items) + "</ul></section>"
        doc = f"""{front}{toc}<main>{body}</main>
{'<section class="refsec"><h2 class="unnum">References</h2><ol class="refs">' + refs + '</ol></section>' if refs else ''}"""
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(spec['short'])}</title>
<style>{css}</style></head><body class="{style}">{doc}</body></html>"""
    hp = HTMLDIR / f"{key}.html"
    hp.write_text(page, encoding="utf-8")
    pdf = OUTDIR / spec["file"]
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--allow-file-access-from-files",
                    f"--print-to-pdf={pdf}", hp.as_uri()], check=True, capture_output=True, timeout=180)
    data = pdf.read_bytes()
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    PAGES[key] = pages
    words = len(re.sub("<[^>]+>", " ", body).split())
    print(f"{key:8s} {pages:3d} pages  {words:6d} words  {nf:2d} figs  {nt:2d} tables  {len(re.findall('<li>', refs)):2d} refs  -> {pdf.name}"
          + ("" if pages >= spec.get("min_pages", 0) else f"   ** BELOW MINIMUM {spec['min_pages']} **"))


if __name__ == "__main__":
    want = sys.argv[1:] or list(DOCS)
    if "Checklist" in want:  # needs the page counts of the others
        want = [k for k in want if k != "Checklist"] + ["Checklist"]
        for k in DOCS:
            if k not in want and (OUTDIR / DOCS[k]["file"]).exists():
                PAGES[k] = len(re.findall(rb"/Type\s*/Page[^s]", (OUTDIR / DOCS[k]["file"]).read_bytes()))
    for k in want:
        build(k, DOCS[k])
