---
name: md
description: Author standalone written deliverables as Markdown (.md) files — reports, guides, READMEs, technical documentation, how-tos, notes, plans, articles, and long-form creative writing — and convert existing content into a clean .md file or render Markdown to HTML/PDF for sharing. Use this skill whenever the user asks to "write a report/guide/article/README/doc", to "save/download as Markdown", mentions a .md file, or wants a polished written document that isn't specifically a Word/PowerPoint/Excel file. Prefer this over inline chat output whenever the result is a document the user will keep, edit, publish, or share — even if they phrase the request casually ("just write a quick post"). Do NOT use for Word documents (use docx), slide decks (use pptx), or spreadsheets (use xlsx).
---

# Markdown Documents

Create well-structured Markdown files for standalone written content. Markdown is the
right default for any text deliverable the user will keep or edit, unless they specifically
want a Word/PowerPoint/Excel file.

## Step 1: Decide file vs. inline

Create a `.md` **file** when the output is a standalone artifact the user will copy,
publish, save, or edit elsewhere: reports, guides, READMEs, documentation, how-tos,
plans/specs, articles, blog posts, release notes, meeting notes, long-form creative writing.
Casual phrasing ("write me a quick post") does not change this — it's still a file.

Answer **inline** (no file) when the content is something read once in the chat: a short
explanation, a summary, a brainstorm, an outline, an answer to a question, or web-search
results. When in doubt between a file and a short inline reply, and the user didn't ask for
a file, lean inline — but anything that reads as a "document" should be a file.

Pick a different skill when the user specifically wants Word (`docx`), slides (`pptx`),
or a spreadsheet (`xlsx`).

## Step 2: Write the file

Create the document in the working directory first, then copy the final version to
`/mnt/user-data/outputs/`. Use a clear, lowercase, hyphenated filename
(e.g. `onboarding-guide.md`, not `Document1.md`).

For anything longer than a short note, draft a quick outline of the sections before writing
prose, then fill each section. Review the whole file once with fresh eyes before delivering.

## Markdown style rules

The goal is a document that is clean both as raw text and when rendered. Follow these:

**One H1, then nest logically.** Exactly one top-level `#` title. Use `##` for major
sections and `###` for subsections. Don't skip levels (no `#` straight to `###`).

**Format with restraint.** Bold is for genuine emphasis or labels, not decoration. Don't
bold whole sentences or every list lead-in. Italics for light emphasis or terms. Avoid
walls of formatting — most body text should be plain prose.

**Prefer prose; use lists when the content is genuinely a list.** Steps, options, and
enumerations belong in lists. Explanations and arguments belong in paragraphs. Don't
shatter a coherent explanation into disconnected bullets.

**Fence code with a language tag** so it highlights and is unambiguous:

````markdown
```python
def greet(name): return f"hi {name}"
```
````

Use inline `` `code` `` for file names, commands, identifiers, and literal values.

**Use GitHub-Flavored Markdown (GFM) features** where they add clarity: tables for true
tabular data, `- [ ]` task lists for checklists, `> ` blockquotes for callouts/quotes,
`---` for major section breaks, footnotes for asides. Don't force a table onto prose.

**Links:** use descriptive text — `[the install guide](url)`, never a bare URL as the link
text when a label would read better.

**Whitespace:** one blank line between block elements (paragraphs, headings, lists, code
fences). This is what makes raw Markdown readable and renders reliably across viewers.

**Optional YAML frontmatter** at the very top when the document benefits from metadata
(title, author, date), e.g. for content destined for a static-site generator:

```markdown
---
title: Onboarding Guide
date: 2026-06-30
---
```

Omit it for general documents where it adds nothing.

For ready-made starting structures (report, README, how-to guide, spec, meeting notes),
see `references/templates.md` and adapt the closest fit rather than inventing structure
from scratch.

## Step 3: Validate and deliver

Before delivering, sanity-check the raw file: exactly one H1, heading levels don't skip,
every code fence is closed and tagged, blank lines separate blocks, no stray formatting.

Then present the `.md` file from `/mnt/user-data/outputs/` so the user can view and
download it.

## Optional: render to HTML or PDF for sharing

When the user wants a shareable/printable version (not just the `.md`), convert with
`pandoc`. See `references/conversion.md` for ready commands (HTML with a clean stylesheet,
PDF, and self-contained single-file HTML). Always keep and deliver the source `.md` too —
it stays editable; the rendered file is the read-only output.
