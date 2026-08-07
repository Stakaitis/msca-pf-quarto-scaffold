# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────
# MSCA-PF proposal toolchain — Quarto + TinyTeX + poppler + PyMuPDF, pinned.
#
# Base : debian:bookworm-slim                          (~30 MB)
# Deps : pixi -> quarto, python, poppler, pymupdf via pixi.lock  (~2.5 GB)
# TeX  : TinyTeX + the packages tex/msca-header.tex needs (~700 MB)
# Total: ~3.5 GB on disk (measured). Big, but it is a frozen LaTeX
#        distribution — that is the whole point: no CTAN fetch at render
#        time, byte-identical PDFs on any laptop, any year.
#
# VERIFIED 2026-08-03: renders Part B-1 with `--network none` (fully
# offline) to 9/10 pages with all four TeX Gyre Termes faces embedded.
#
# WHY THIS EXISTS: `pixi install` alone pins Quarto/Python/poppler/PyMuPDF, but
# TinyTeX still downloads LaTeX packages from CTAN on first render. That
# step is networked and mutable, so it is the one part of the build that
# can drift or fail offline. This image bakes it in.
#
# ARCHITECTURE: amd64 only, and that is not a preference — conda-forge ships no
# `quarto` build for linux-aarch64, so the environment cannot solve on ARM. On an
# Apple Silicon Mac this runs under emulation: slower, but it means everyone gets
# the identical image. --platform is required in every command below.
#
# Build (from the folder holding pixi.toml):
#   docker build --platform linux/amd64 -t msca:latest .
#
# Render the proposal (mount your project, outputs land in _build/):
#   docker run --rm --platform linux/amd64 -v "$PWD:/work" msca:latest pixi run build
#
# Live preview on http://localhost:4200 :
#   docker run --rm --platform linux/amd64 -p 4200:4200 -v "$PWD:/work" msca:latest \
#     pixi run quarto preview partB1.qmd --to html --port 4200 --host 0.0.0.0
#
# Shell inside, to poke around:
#   docker run --rm -it --platform linux/amd64 -v "$PWD:/work" --entrypoint bash msca:latest
# ─────────────────────────────────────────────────────────────────
FROM --platform=linux/amd64 debian:bookworm-slim

# perl  — tlmgr is a perl program, TinyTeX will not run without it
# xz-utils — TinyTeX ships as .tar.xz; without it the install dies in tar
# fontconfig — lets LaTeX find the embedded Type1 fonts reliably
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl perl xz-utils fontconfig \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://pixi.sh/install.sh | bash
ENV PATH="/root/.pixi/bin:${PATH}"

WORKDIR /opt/toolchain

# Solve the environment from the lock file, so the container gets exactly the
# Quarto/Python/poppler/PyMuPDF builds the lock records — not "whatever is current".
COPY pixi.toml pixi.lock ./
RUN pixi install --locked

# TinyTeX, then pre-install every LaTeX package tex/msca-header.tex pulls in.
# Listing them explicitly (rather than letting the first render fetch them) is
# what makes an offline render possible.
RUN pixi run quarto install tinytex --no-prompt
# Symlink rather than hardcode /root/.TinyTeX/bin/<arch>/ — the arch directory
# name is not stable across TinyTeX releases.
RUN for d in /root/.TinyTeX/bin/*/; do ln -sf "$d"* /usr/local/bin/; done && tlmgr --version
RUN tlmgr install \
        tgtermes textcomp newtx newunicodechar fancyhdr lastpage \
        titlesec enumitem caption microtype \
        geometry hyperref xcolor booktabs longtable etoolbox \
        koma-script unicode-math upquote fvextra footnotebackref \
        selnolig bookmark xurl 2>&1 | tail -5 || true

# Prove the LaTeX stack works at build time rather than discovering a missing
# package on the user's first render. Uses the real header, then discards output.
COPY tex/ ./tex/
# The probe's _quarto.yml mirrors the real one's geometry block on purpose.
# Without it Quarto never loads the geometry package, \geometry{heightrounded}
# in the header is undefined, and the probe fails on a document the real
# build renders fine -- a false alarm that costs a full image rebuild to read.
RUN printf 'project:\n  output-dir: _probe\nformat:\n  pdf:\n    pdf-engine: pdflatex\n    include-in-header: tex/msca-header.tex\n    geometry: [a4paper, top=16mm, bottom=16mm, left=16mm, right=16mm]\n' > _quarto.yml \
 && printf -- '---\ntitle: probe\n---\n\nBuild probe: %s %s %s alpha beta gamma.\n' '>=' 'x' 'degree' > probe.qmd \
 && pixi run quarto render probe.qmd --to pdf \
 && test -f _probe/probe.pdf \
 && echo "LaTeX stack OK" \
 && rm -rf _probe probe.qmd _quarto.yml tex

# Put the solved environment straight on PATH. This matters: the project folder
# you mount at /work carries its own .pixi/ built for macOS, and `pixi run` there
# would try to use that and fail on platform mismatch. Calling quarto/python
# directly sidesteps the mounted env entirely.
ENV CONDA_PREFIX="/opt/toolchain/.pixi/envs/default"
ENV PATH="${CONDA_PREFIX}/bin:${PATH}"

# conda-forge's quarto is a shell wrapper that needs QUARTO_DENO, QUARTO_PANDOC,
# DENO_DOM_PLUGIN and friends — normally set by conda activation. Sourcing the
# packages' own activate.d scripts is better than hardcoding that list here,
# because it keeps working when the feedstock changes which vars it sets.
RUN printf '#!/bin/sh\nfor f in "$CONDA_PREFIX"/etc/conda/activate.d/*.sh; do [ -r "$f" ] && . "$f"; done\nexec "$@"\n' \
      > /usr/local/bin/entrypoint.sh \
 && chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /work
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# Default: exactly what `pixi run build` does on the host — render every part,
# then validate every PDF against the full MSCA formatting rule set (A4, Times,
# 11 pt, 15 mm, footer, page cap, placeholders). Non-zero exit on any failure.
# Override with any command, e.g. `quarto render partB2.qmd`.
# Uses render.sh, not a bare `quarto render`: project mode fails intermittently
# partway through and leaves a stale PDF that still measures as valid.
CMD ["sh", "-c", "sh scripts/build/render.sh && sh scripts/check/run.sh"]
