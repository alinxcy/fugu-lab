---
name: dataviz
description: Use whenever you are about to create ANY chart, graph, plot, dashboard, or data visualization in any medium (HTML/React artifact, SVG, matplotlib/plotly/d3/Recharts, PNG). Read BEFORE writing chart code or choosing chart colors.
---

> **RECONSTRUCTION** — approximation of the Claude Code built-in `dataviz`, not the official text.

# dataviz

Produce visualizations that read as one coherent, accessible system in both light and dark.

## Principles
1. **Form follows question**: pick the chart type from what the data must show (trend→line, compare→bar, part-of-whole→stacked/donut sparingly, correlation→scatter).
2. **Color with intent**: a small categorical palette; sequential for ordered data; diverging for ±. Ensure contrast in light AND dark.
3. **Mark specs**: sensible stroke widths, tick density, direct labels over legends where possible.
4. **Interaction**: tooltips that add info, not noise; keyboard/focus states for HTML.
5. Validate accessibility (contrast, color-blind safety) before shipping.
