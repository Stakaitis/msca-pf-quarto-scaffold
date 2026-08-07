# MSCA-PF proposal scaffold — write the content, forget the formatting

A [Quarto](https://quarto.org) scaffold for a **Marie Skłodowska-Curie Postdoctoral
Fellowship** Part B. Every formatting rule the call imposes is enforced by the build,
which **measures the finished PDF** and fails if it does not comply.

Nothing here is specific to one proposal. The section files ship as skeletons carrying
the official sub-section headings and the evaluator's questions as comments.

## Why bother

MSCA makes everything past page 10 **invisible to evaluators**. An overflow does not
error — it silently deletes your Implementation tables. And formatting is easy to break
without noticing: this scaffold exists because a render once came out US Letter, in
Latin Modern, with no page footer, and nothing about it looked wrong at a glance.

So the build does not trust the render. It opens the PDF and measures it.

## Quick start

```bash
# 1. one-time: install pixi (https://pixi.sh), then
pixi install          # Quarto, Python, PyMuPDF, poppler — exact versions from pixi.lock
pixi run setup        # TinyTeX, a self-contained LaTeX distribution

# 2. THE command: renders every part, then validates every PDF and Word file
pixi run build

# 3. while writing — live, hot-reloading preview on localhost:4200
pixi run preview
```

`pixi run build` is the only sanctioned build. A bare `quarto render` produces a
document nobody has checked.

No pixi? If Quarto, a TeX engine, poppler and PyMuPDF are already on your `PATH`,
`make build`, `make preview`, `make pdf`, `make b2`, `make check` and `make clean` do
the same. The Makefile calls the tools directly rather than through pixi.

**Full walkthrough: open [`HOW_TO_EDIT_AND_RENDER.html`](HOW_TO_EDIT_AND_RENDER.html)
in a browser.**

## The build fails until you have written it

Straight after cloning, `pixi run build` **fails**, and that is correct:

```
[FAIL] No unresolved placeholders   (hard)
       10 found -- p1: '[acronym] 1. Excellence 1.1 Quality and pertinence of' | p2: '[title] M1-M[x] ...
```

Every `[...]` in the skeletons is a prompt to be replaced. The build refuses to call a
document compliant while any of them survives into the PDF, because an evaluator would
read them as your text. Everything *else* — A4, Times, 11 pt, margins, footer — passes
from the start.

## Where you write

`sections/` holds **one file per scored sub-section**. That is the only directory you
normally open.

| File | Criterion |
|------|-----------|
| `_1.1_objectives.qmd` `_1.2_methodology.qmd` `_1.3_supervision.qmd` `_1.4_researcher.qmd` | Excellence — 50% |
| `_2.1_career.qmd` `_2.2_dissemination.qmd` `_2.3_magnitude.qmd` | Impact — 30% |
| `_3.1_workplan.qmd` `_3.2_host.qmd` | Implementation — 20% |
| `partB2.qmd` | CV, host capacity, ethics, security screening, Green Charter, AI declaration |
| `references.bib` | Bibliography — cite in text with `[@key]` |

One file = one evaluator question, so the thing you edit is the thing that gets scored.
`partB1.qmd` stitches them together in order and is build configuration, not content.

**The build refuses to render if any of the nine is missing or empty.** Each is a
question that would otherwise go silently unanswered — which is exactly how §1.4 gets
lost, at a cost of two scored questions.

Everything else is machinery: `_quarto.yml`, `tex/`, `nature.csl`, `scripts/`.

## What the build measures

**Eight** hard checks on every rendered PDF, and the same rules on every Word file bar
the page limit — seven there, because Word paginates differently and the PDF stays the
authority on length. Any failure exits non-zero:

| Check | Rule |
|-------|------|
| Output is current | the file is newer than every source, so a render that failed cannot pass as one that worked |
| Page size | A4, every page |
| Fonts | Times family for body text, all embedded; Latin Modern rejected outright |
| Font size | body ≥ 11 pt; captions, footers and figure labels ≥ 8 pt |
| Margins | ≥ 15 mm all four sides, measured from the content, images and vector ink included |
| Footer | `Part B - Page X of Y` on every page, with a correct total |
| Page limit | Part B-1 ≤ 10 pages |
| Placeholders | no `[...]`, `TODO cite` or stray `**` left in the text |

Plus three warnings, which do not fail the build: cover page / table of contents,
reference-list page span, and PDF version.

## Word output

`pixi run build` renders `.docx` alongside the PDF, styled to match: A4, 16 mm margins,
Times New Roman 11 pt, same footer. `tex/msca-reference.docx` supplies those defaults;
regenerate it with `pixi run refdoc`.

**Word will not paginate identically to LaTeX.** The two break lines differently, so the
same text at the same size lands on different pages. The Word file matches on *style*;
the PDF remains the authority for the 10-page limit.

## All tasks

| Command | What it does |
|---------|--------------|
| `pixi run build` | **The entry point.** Renders every part, validates every output. |
| `pixi run all` | Alias for `build` — older muscle memory still lands on the checked build |
| `pixi run preview` | Live hot-reloading HTML on `localhost:4200` |
| `pixi run pdf` | Part B-1 alone + its checks — a faster loop while writing |
| `pixi run b2` | Part B-2 alone + its checks |
| `pixi run check` | Re-run the checks on the last build, without rendering |
| `pixi run gantt` | Render `gantt.yaml` to `figures/gantt.pdf` at text-column width |
| `pixi run refdoc` | Regenerate the Word reference document |
| `pixi run hooks` | Install a pre-commit hook that blocks committing a failing PDF |
| `pixi run docx` | Both parts to Word, without rendering the PDFs |
| `pixi run proof` | Part B-1 to Word and opens it, for a Grammarly pass (macOS only) |
| `pixi run clean` | Delete build artefacts |

## Live preview — two Quarto behaviours this works around

1. **`quarto preview` watches only the file you name.** Files pulled in with
   `{{< include >}}` are *not* watched, so editing a section leaves the preview silently
   stale. `scripts/build/preview.sh` nudges the master file when a section changes.
2. **`quarto preview` pointed at PDF renders once, then fails on every rebuild.** The
   live loop therefore runs on HTML, which reloads cleanly.

HTML shows prose and flow; it cannot show pagination. Use `pixi run build` for that.

`scripts/build/render.sh` also renders each document individually rather than using
project mode, which fails intermittently with a `rename … NotFound` error partway
through — leaving a stale PDF behind that still measures as valid.

## Reproducible builds

`pixi.toml` + `pixi.lock` pin every tool. The one remaining variable is TinyTeX
fetching LaTeX packages from CTAN at first render. The `Dockerfile` freezes that too:

```bash
docker build --platform linux/amd64 -t msca:latest .
docker run --rm --platform linux/amd64 --network none -v "$PWD:/work" msca:latest
```

That renders and validates with **no network at all**.

amd64 only, and not by preference: conda-forge publishes no `quarto` build for
`linux-aarch64`, so the environment cannot solve on ARM. On Apple Silicon it emulates.

## Adapting it to a different call

| What | Where |
|------|-------|
| Page cap | `PART_B1_PAGE_LIMIT` in `scripts/check/lib/rules.py` — one constant; callers pass `--part-b1` |
| Required sub-sections | the `required` list in `scripts/build/render.sh` |
| Margins, font size, citation style | `_quarto.yml` |
| Font, footer text, Unicode mappings | `tex/msca-header.tex` |
| Word styling | `scripts/word/make_reference.py`, then `pixi run refdoc` |

Swap `nature.csl` for any style from [zotero.org/styles](https://www.zotero.org/styles).

Re-check the formatting rules against the current call's application form before
reusing this — they are reissued each year.

## Repository conventions

This layout is deliberate and portable. If you are starting a new repository,
these are the rules worth copying.

**One directory per task, not one directory per file type.** `scripts/` is grouped
by *what the code does*, so finding the compliance gate means opening `check/`
rather than scanning thirty filenames:

```
scripts/
├── build/     render.sh, preview.sh          producing documents
├── check/     run.sh, compliance.py, lib/    verifying them
├── gantt/     make.py, vendor/               the chart
├── word/      make_reference.py              Word styling
└── hooks/     install.sh                     git integration
```

**One file per rule.** `check/lib/checks/` has a module per formatting rule —
`margins.py`, `fonts.py`, `page_size.py`. Each is 30–140 lines, knows nothing
about the others, and can be read in one sitting. They were split out of a
single 1,166-line file; nothing about the behaviour changed, and every one of
them is now findable by name.

**A registry does the wiring.** `check/lib/checks/__init__.py` imports each rule
and declares the order once. Adding a rule is a new file plus one line there —
no other file changes. That is the pattern to reach for whenever a pipeline
grows past three steps.

**Separate the values from the logic.** Every threshold and pattern lives in
`check/lib/rules.py`. Changing what compliance *means* is a one-file edit; the
code that measures never moves.

**Vendored code is quarantined and labelled.** `scripts/gantt/vendor/` holds
third-party code copied in verbatim, with `PROVENANCE.md` recording where it
came from and how to re-sync. Nothing else in the repo edits those files.

**Say why, not what.** Comments here record the measurement or the failure that
motivated a line — "a 1400 px canvas is 370 mm wide, and Quarto scaling it
shrinks the labels below the 8 pt floor". A comment that restates the code
rots; one that records a reason stays useful.

**Make the guardrails executable.** Every rule this project cares about is
checked by something that fails the build. Documentation describing a rule is a
wish; a check enforcing it is a fact.

## Licence

MIT — see [LICENSE](LICENSE). Third-party components are listed in [NOTICE](NOTICE).
