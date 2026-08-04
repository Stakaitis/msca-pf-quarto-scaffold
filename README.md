# MSCA-PF proposal scaffold — write the content, forget the formatting

A [Quarto](https://quarto.org) scaffold for a **Marie Skłodowska-Curie Postdoctoral
Fellowship** Part B. Every formatting rule the call imposes is baked into the build,
so you only ever edit prose. Each build also checks that Part B-1 still fits inside
the 10-page limit — and **fails** if it does not.

Nothing here is specific to one proposal: the section files ship as empty skeletons
with the evaluator's questions written in as comments.

## Why bother

MSCA makes everything past page 10 **invisible to evaluators**. An overflow does not
error — it silently deletes your Implementation tables. That one fact is the reason
this scaffold exists: the page count is checked on every single build.

## Quick start

```bash
# 1. one-time: install pixi (https://pixi.sh), then
pixi install          # Quarto, Python, poppler — exact versions from pixi.lock
pixi run setup        # TinyTeX, a self-contained LaTeX distribution

# 2. the command you will run most
pixi run pdf          # renders _build/partB1.pdf, then enforces the page limit

# 3. while writing — live, hot-reloading preview on localhost:4200
pixi run preview
```

No pixi? If Quarto, a TeX engine and poppler are already on your `PATH`, the
`Makefile` covers the core tasks: `make pdf`, `make preview`, `make b2`,
`make check`, `make clean`. (`docx`, `proof` and `method` are pixi-only.)

**Full walkthrough: open [`HOW_TO_EDIT_AND_RENDER.html`](HOW_TO_EDIT_AND_RENDER.html)
in a browser.** It covers setting up a clean laptop from zero, the daily writing loop,
citations, the Grammarly workflow, and troubleshooting.

## The gate fails until you have written it

Straight after cloning, `pixi run build` **fails**, and that is correct:

```
[FAIL] No unresolved placeholders   17 found -- '[Verb] [what, in WP1]' ...
```

Every `[...]` in the skeletons is a prompt to be replaced. The build refuses to
call a document compliant while any of them survives into the PDF, because an
evaluator would read them as your text. Replace them and the check goes green.
Everything *else* — A4, Times, 11 pt, margins, footer — passes from the start.

## Where you write

| File | What it is |
|------|-----------|
| `sections/_excellence.qmd` | Section 1 — Excellence (1.1 objectives, 1.2 methodology, 1.3 supervision, **1.4 your experience**) |
| `sections/_impact.qmd` | Section 2 — Impact (2.1 career, 2.2 dissemination, 2.3 magnitude) |
| `sections/_implementation.qmd` | Section 3 — Implementation (work plan, Gantt, milestones, risk table) |
| `partB2.qmd` | Part B-2 — CV, host capacity, ethics, AI declaration, Green Charter |
| `references.bib` | Bibliography — cite in text with `[@key]` |
| `partB1.qmd` | Master file that stitches the three sections together; you rarely touch it |

Everything else is machinery: `_quarto.yml`, `tex/msca-header.tex`, `nature.csl`,
`scripts/`. Editing those can break compliance in ways the build will not warn you about.

> **§1.4 is easy to lose.** "Quality and appropriateness of the researcher's professional
> experience, competences and skills" is a required Part B-1 subsection under the
> 50%-weighted Excellence criterion — it is the evaluator's question 14. It is *not* the
> Part B-2 CV. The skeleton includes it so you do not omit it by accident.

## What is enforced automatically

- **A4**, **16 mm** margins on all sides (safely above the 15 mm minimum)
- **TeX Gyre Termes** — the free font metric-compatible with Times New Roman, accepted
  as Nimbus Roman No. 9 L — **embedded** in the PDF, as the call requires
- **11 pt** body minimum, **single** spacing; **tables stay at 11 pt**
- Footer `Part B - Page X of Y`; captions and footnotes ≥ 8 pt
- **No cover page, no table of contents**
- **Part B-1 hard-capped at 10 pages** — see `scripts/check_pagecount.py`
- Compact **superscript numeric citations**, which save far more space than they cost

## All tasks

| Command | What it does |
|---------|--------------|
| `pixi run pdf` | Part B-1 + page check. Your main command. |
| `pixi run preview` | Live hot-reloading HTML on `localhost:4200` |
| `pixi run b2` | Part B-2 (no page limit) |
| `pixi run docx` | Both parts as Word files |
| `pixi run proof` | Word file for a Grammarly or supervisor pass, and opens it |
| `pixi run all` | Both parts + page check |
| `pixi run check` | Re-run the page check without rendering |
| `pixi run clean` | Delete build artefacts |

## Live preview — two Quarto gotchas this works around

Both verified against Quarto 1.9.38 on 2026-08-03:

1. **`quarto preview` watches only the file you name.** Files pulled in with
   `{{< include >}}` are *not* watched, so editing a `sections/*.qmd` file leaves the
   preview silently stale — old text, no error. `scripts/preview.sh` nudges the master
   file when a section changes.
2. **`quarto preview` to PDF renders once, then fails on every rebuild.** The live loop
   therefore runs on HTML, which reloads cleanly.

HTML shows prose and flow; it cannot show pagination. Use `pixi run pdf` for that.

## Reproducible builds

`pixi.toml` + `pixi.lock` pin Quarto, Python and poppler from conda-forge. The one
remaining variable is TinyTeX fetching LaTeX packages from CTAN at first render —
networked and mutable. The `Dockerfile` freezes that too:

```bash
docker build --platform linux/amd64 -t msca:latest .
docker run --rm --platform linux/amd64 --network none -v "$PWD:/work" msca:latest
```

That renders with **no network at all**. Verified 2026-08-03: identical PDF, correct
page count, all fonts embedded.

The image is amd64-only, and that is not a preference — conda-forge publishes no
`quarto` build for `linux-aarch64`, so the environment cannot solve on ARM. On Apple
Silicon it runs under emulation.

## Adapting it to a different funder

Three files carry the call-specific rules:

| File | What to change |
|------|----------------|
| `pixi.toml` / `Makefile` | The page cap, passed as the last argument to `check_pagecount.py` |
| `tex/msca-header.tex` | Font, and the `Part B - Page X of Y` footer text |
| `_quarto.yml` | Margins (`geometry:`), font size, citation style (`csl:`) |

Swap `nature.csl` for any of the thousands at [zotero.org/styles](https://www.zotero.org/styles).

## Licence

MIT — see [LICENSE](LICENSE). `nature.csl` is redistributed from the
[CSL styles repository](https://github.com/citation-style-language/styles) under
CC BY-SA 3.0.
