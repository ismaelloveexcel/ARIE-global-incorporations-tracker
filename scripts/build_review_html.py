from pathlib import Path

root = Path(__file__).resolve().parents[1]
src = (root / "app/static/index.html").read_text(encoding="utf-8")
header = """<!DOCTYPE html>
<!--
  REVIEW COPY — Arie Incorporation Monitor (revised markup)
  Production: app/static/index.html
  Checklist: docs/UI_DONE_CHECKLIST.md
  Local preview uses relative paths to app/static for CSS and JS.
-->
"""
if src.startswith("<!DOCTYPE"):
    idx = src.find("<html")
    src = src[idx:]
src = src.replace('href="/static/styles.css"', 'href="../../app/static/styles.css"')
src = src.replace('src="/static/app.js"', 'src="../../app/static/app.js"')
src = src.replace("<title>Arie Finance", "<title>[Review] Arie Finance")
out = header + src
dest = root / "docs/review/index-revised.html"
dest.write_text(out, encoding="utf-8")
if "motion" in out.lower():
    raise SystemExit("invalid motion tag in output")
print("Wrote", dest)
