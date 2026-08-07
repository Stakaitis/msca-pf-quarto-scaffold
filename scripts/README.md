# scripts/ — what runs, in what order, producing what

You do not run anything in here directly. `pixi run build` is the entry point;
everything below is what it calls. This file exists so the pipeline can be read
in one place instead of reconstructed from five.

## The flow

```
  YOU EDIT                    BUILD                         GATE
  ────────                    ─────                         ────

  sections/                                                 for each output:
    _1.1_objectives.qmd  ┐                                    freshness
    _1.2_methodology.qmd │                                    page size
    _1.3_supervision.qmd │  {{< include >}}                   fonts
    _1.4_researcher.qmd  ├─────────────┐                      font sizes
    _2.1_career.qmd      │             │                      margins
    _2.2_dissemination…  │             ▼                      footer
    _2.3_magnitude.qmd   │        partB1.qmd ─┐               page limit ¹
    _3.1_workplan.qmd    │                    │               placeholders
    _3.2_host.qmd        ┘        partB2.qmd ─┤
                                              │                    │
  partB2.qmd ─────────────────────────────────┤                    │
  references.bib ─────────────────────────────┤                    ▼
  figures/gantt.pdf ──────────────────────────┤              exit 0 or 1
                                              │
                             ┌────────────────┘
                             ▼
                 scripts/build/render.sh
                   one `quarto render` per document ²
                   refuses to start if any of the nine
                   sections is missing or empty
                             │
                             ▼
                          _build/                 ──►  scripts/check/run.sh
                            partB1.pdf   partB1.docx      drives the gate over
                            partB2.pdf   partB2.docx      every file in _build/
```

¹ Part B-1 only. ² Not project mode — see "Why one render per document" below.

Config that shapes the render, rather than being part of it: `_quarto.yml`
(render list, output dir, geometry, both output formats), `tex/msca-header.tex`
(fonts, footer, Unicode), `nature.csl` (citation style).

## Directories

| Directory | Stage | Contents |
|---|---|---|
| `build/` | render | `render.sh` produces every document; `preview.sh` runs the live HTML loop |
| `check/` | gate | `run.sh` drives the gate over `_build/`; `compliance.py` checks one file; `lib/` holds the rules |
| `word/` | setup | `make_reference.py` regenerates the `.docx` style template. Run only when styling changes |
| `gantt/` | asset | `make.py` renders `gantt.yaml` to `figures/gantt.pdf`. Run only when the schedule changes |
| `hooks/` | git | `install.sh` adds a pre-commit hook that blocks committing a failing PDF |

`word/` and `gantt/` are **not** part of `pixi run build`. They produce committed
inputs — a style template and a figure — that the build then consumes. Running
the build never regenerates them, which is why a stale Gantt survives a build.

## Outputs

Everything lands in `_build/`, which is generated and gitignored. Nothing else
should ever be kept there — `pixi run clean` deletes the directory whole.

| Output | Checked with | Page limit |
|---|---|---|
| `_build/partB1.pdf` | `--part-b1` | **10 pages, hard** |
| `_build/partB2.pdf` | `--no-page-limit` | none |
| `_build/*.docx` | `--no-page-limit` | none — Word paginates differently; the PDF is the authority |
| any other `_build/*.pdf` | `--no-page-limit` | none — picked up automatically, so a new document cannot go unchecked |

Eight hard checks per PDF, seven per Word file. Any failure exits non-zero, and
`run.sh` returns the worst status across every file rather than stopping at the
first.

## Adding a rule to the gate

One new file in `check/lib/checks/`, one line in `check/lib/checks/__init__.py`.
Nothing else changes — that registry is the only place the running order is
declared. Thresholds and patterns belong in `check/lib/rules.py`, never inline.

## Why one render per document

`quarto render` in project mode fails intermittently partway through with a
`rename … NotFound` error. It leaves the previous PDF in `_build/`, which still
measures as perfectly valid — a passing build of a document that was never
produced. `render.sh` therefore renders each document individually and verifies
each expected output appeared. The freshness check is the second line of defence
against the same failure.
