"""
Local CLI render — geometry/typography inspection before any wiring.

    python tools/w7_local.py --template "Dot Grid" --body 120 \
        --title "The Keeping Book" --subtitle "A Gardener's Log Journal" \
        --author "E. J. Sandoval" --out keeping_book.pdf
"""

import argparse
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from render import build_interior  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--template", required=True)
    p.add_argument("--body", type=int, default=120)
    p.add_argument("--title", required=True)
    p.add_argument("--subtitle", default=None)
    p.add_argument("--author", required=True)
    p.add_argument("--isbn", default=None)
    p.add_argument("--year", type=int, default=2026)
    p.add_argument("--prompts-file", default=None,
                   help="one prompt per line (Prompted template)")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    prompts = None
    if args.prompts_file:
        with open(args.prompts_file, encoding="utf-8") as f:
            prompts = [ln.strip() for ln in f if ln.strip()]

    pdf, params = build_interior(
        title=args.title, subtitle=args.subtitle, author=args.author,
        template=args.template, body_pages=args.body,
        copyright_year=args.year, isbn=args.isbn, prompts=prompts)
    with open(args.out, "wb") as f:
        f.write(pdf)
    print(f"{args.out}: {len(pdf)} bytes, "
          f"sha256 {hashlib.sha256(pdf).hexdigest()[:16]}")
    print(params)


if __name__ == "__main__":
    main()
