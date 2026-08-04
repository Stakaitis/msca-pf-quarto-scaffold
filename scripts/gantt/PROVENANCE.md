# Vendored from lab-tools

`gantt.py` and `lib_plot_themes.py` are copied verbatim from
`General_tools/gantt/` and `General_tools/` in the lab-tools repository.

Vendored rather than referenced so this proposal builds on any machine and
inside the Docker image, with no dependency on a sibling checkout.

To re-sync after upstream changes:

    cp ~/Scripts/General_tools/gantt/gantt.py \
       ~/Scripts/General_tools/lib_plot_themes.py \
       work/scripts/gantt/

Do not edit these two files here — MSCA-specific settings live in
`scripts/make_gantt.py`, which drives them. Editing in place makes the next
re-sync silently discard your changes.
