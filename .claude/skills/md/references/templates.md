# Markdown Document Templates

Adapt the closest template instead of inventing structure. Delete sections that don't apply;
don't pad a short document with empty headings.

## Report / analysis

```markdown
# [Title]

Brief framing sentence: what this covers and why it matters.

## Summary

2–4 sentences with the key takeaway up front, for readers who stop here.

## Background / context

What the reader needs to understand the rest.

## Findings

The substance. Use `###` subsections per theme. Tables for data, prose for reasoning.

## Recommendations / next steps

Concrete, ordered actions.

## Appendix

Supporting detail, raw data, references.
```

## README (project)

```markdown
# Project Name

One-line description of what it does.

## Features

- Key capability 1
- Key capability 2

## Install

```bash
<install commands>
```

## Usage

```bash
<minimal example>
```

## Configuration

Key options, environment variables, config files.

## License
```

## How-to guide / tutorial

```markdown
# How to [accomplish task]

What you'll end up with, and roughly how long it takes.

## Prerequisites

- Requirement 1
- Requirement 2

## Steps

1. First action — what to do and what you should see.
2. Next action.
3. ...

## Troubleshooting

Common failure → cause → fix.

## See also

Links to related material.
```

## Technical spec / design doc

```markdown
# [Component] Design

## Goal

The problem this solves, in 1–2 sentences.

## Non-goals

Explicitly out of scope, to prevent scope creep.

## Design

How it works. Diagrams (ASCII or linked), data structures, interfaces.

## Alternatives considered

Option → why not chosen.

## Risks / open questions
```

## Meeting / decision notes

```markdown
# [Topic] — [Date]

**Attendees:** ...

## Decisions

- [x] Decided: ... (owner)

## Action items

- [ ] Task — owner — due date

## Discussion

Context and notable points.
```
