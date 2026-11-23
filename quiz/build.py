#!/usr/bin/env python3
"""Embed quiz_questions.json into src/app.html and write index.html (standalone page)."""
import json, pathlib, sys
here = pathlib.Path(__file__).parent
bank = json.loads((here / "quiz_questions.json").read_text(encoding="utf-8"))
data = json.dumps(bank, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
body = (here / "src" / "app.html").read_text(encoding="utf-8").replace("/*__QUESTIONS__*/[]", data, 1)
page = ('<!doctype html>\n<html lang="es">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        + body + '\n</html>\n')
(here / "index.html").write_text(page, encoding="utf-8")
if len(sys.argv) > 1:  # optional: body-only output (no doctype wrapper)
    pathlib.Path(sys.argv[1]).write_text(body, encoding="utf-8")
print(f"index.html: {len(bank)} preguntas, {len(page)//1024} KB")
