# Rendering Markdown to HTML / PDF

Use `pandoc` to produce a shareable or printable version. Always keep and deliver the
source `.md` alongside the rendered file — the `.md` stays editable; the rendered file is
the final read-only output. Render from the working copy, then copy results to
`/mnt/user-data/outputs/`.

## Self-contained HTML (best default for sharing)

One file, no external assets, opens in any browser:

```bash
pandoc input.md -o output.html \
  --standalone --embed-resources \
  --metadata title="Document Title" \
  --highlight-style=tango
```

For a cleaner look, supply a stylesheet with `--css style.css` (with `--embed-resources`
the CSS is inlined into the single file).

## PDF

Requires a PDF engine. `wkhtmltopdf` (via HTML) is forgiving and needs no LaTeX:

```bash
pandoc input.md -o output.pdf --pdf-engine=wkhtmltopdf
```

If a LaTeX toolchain is available, this gives typographically nicer output:

```bash
pandoc input.md -o output.pdf --pdf-engine=xelatex -V geometry:margin=1in
```

If neither engine is installed, render to standalone HTML instead and tell the user they
can print-to-PDF from the browser.

## Table of contents and section numbering

For long documents:

```bash
pandoc input.md -o output.html --standalone --embed-resources --toc --toc-depth=3
```

Add `--number-sections` to number headings.

## GitHub-flavored input

If the source uses GFM features (task lists, tables, strikethrough), parse it explicitly:

```bash
pandoc -f gfm input.md -o output.html --standalone --embed-resources
```

## Notes

- Verify the engine exists first (e.g. `which wkhtmltopdf`) and fall back gracefully.
- Check the rendered file actually got created before presenting it.
- Don't delete or overwrite the source `.md`.
