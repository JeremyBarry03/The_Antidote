# Project overview

`paper.tex` is the standalone source for the web overview and PDF. Edit the content
there, page structure in `template.html`, and web presentation in `style.css` and
`research.mjs`. Run `python3 Frontend/research/build.py` from the repository root
with Pandoc and pdfLaTeX on PATH. Rebuild rather than editing generated
`index.html` or `paper.pdf`; compiler files stay in the ignored
`Data_Science/artifacts/research_paper/` directory. The PDF deliberately uses
conventional LaTeX article typography.

The Python service serves `/overview/`, the two overview downloads, and the page's
CSS/module explicitly. The template and build source are not HTTP assets. Replay
navigation links at the top and bottom say Overview and open it in a separate
tab; overview links return to the replay.

## Continuity evidence

Source comparison of this page's `style.css` with `../tracking/style.css` confirms
the same neutral colors. The overview's background maps to the replay's ground,
and its border maps to the replay's strong border.

| Role | Dark | Light |
|---|---|---|
| Background | `#090a0c` | `#fafafa` |
| Surface | `#121417` | `#f2f2f2` |
| Text | `#e7eaf1` | `#19191b` |
| Muted text | `#b2b8c8` | `#57575f` |
| Rule | `#242932` | `#e0e0e4` |
| Strong border | `#535b69` | `#9999a1` |

Both pages load the existing Geist Mono asset. The reading hierarchy uses a
15px/1.9 body, a 75ch text measure, and 40/24/17px title and heading sizes on
desktop; below 900px the body is 14px, and at 480px and below the title is 32px.
Thin rules and ordinary links carry the structure. `research.mjs` imports `../tracking/appearance.mjs`,
sharing the Invert control and its `antidote-appearance` saved preference.

Contents open on desktop at 900px and above, beside the overview in a sticky rail;
smaller screens start with a native disclosure above the text. Pandoc generates
native MathML without an external math runtime. Display equations scroll
horizontally inside labeled regions with `tabindex="0"`; those regions and the
table regions receive a 2px muted focus outline with a 5px offset. These reading
adaptations preserve the replay's visual identity. No new shipping rasters are used.

## Evaluation boundary

The current serving bundle includes frozen A/B/nominal-C models fitted using
2023 data and a full-March 2024 nominal comparison (5,382 decisions, 243
approaches, 219 vessels). The available fit partition is January 1--June 29,
2023, with model selection on June 30--July 19; this is not yet the requested
fit on all eligible 2023 data. March has already been explored during model
selection and is not an untouched confirmation period.

The eight-control graph bundle contains 256 precomputed on/off scenarios at a
fixed 25% strength, beginning March 15, across six sampled March approaches.
It is separate from the continuous live replay sliders and does not establish
full-cohort mitigation performance. Separate same-case April follow-up reports
measure the missing-speed, missing-course, and missing-vessel-class repairs on
112 approaches. They do not establish an all-eight or combined-repair gain, or
a full-March repair comparison. The 2023 source files are not part of the tracked
serving bundle; hashes are recorded, but exact retraining needs matching
authorized sources. Human-reviewed error types are saved as feedback for
versioned retraining; each candidate still needs evaluation before it can
replace a frozen model. Operator effort is unmeasured, and the overview does not
claim a completed operator study or operational readiness.

## Editorial coverage

The public overview uses subject headings, not judging labels. Internal mapping:

| Rubric | Evidence in the overview or existing replay |
|---|---|
| E1 | User, resource decision, consequences, crossing proxy, measurable goals |
| E2 | Model roles, A/B comparators, frozen inference, setup; working replay remains the artifact |
| E3 | Full-March nominal comparison; sampled attack scenarios, denominators, and uncertainty boundaries |
| E4 | Human error-type review, saved feedback for retraining, conditional correction and escalation; human time remains unmeasured |
| E5 | Product provenance, rights constraints, identifiers, representation risks, proposed accountable roles |
| E6 | Iterate decision, responsible roles, resources, approvals and decision checkpoint |
| E7 | Versions, hashes, sources, setup, source/PDF downloads; recorded fallback remains a separate artifact |
| C1 | Receipt-time contract and report age; live gap control with fixed delayed-report stress comparison |
| C2 | Specific faults; source-volume effects remain to be measured against the current model version |
| C3 | Eight-control ordered replay and fixed-strength saved scenario progression |
| C4 | Same-case April follow-up ablations for missing speed/course/class with uncertainty and scope limits; full-March, all-eight, and combined-repair evaluation remains open |

## Direction contract

THESIS: A readable technical overview extending the existing monochrome demo. The
reader inspects the mathematics and evidence, then returns to the live replay.

OWN-WORLD: The replay's exact dark/light neutral palette and Geist Mono typography, shared
Invert preference, thin rules, mathematical notation, and ordinary linked references.
The web page stays in the demo's visual world; the PDF uses conventional LaTeX
article typography.

STORY: Decision and reference; causal data; model choices; deterioration and
repairs; measured results and current limits; oversight; governance; next study.

FIRST VIEWPORT: Project navigation above a left-aligned project title, descriptive
subtitle, and links to the replay and results. Desktop contents rail beside the
short At a glance introduction; mobile contents disclosure above the text.
No metric cards or new replay controls.

FORM: Project overview inside the established visual system;
code-led extension with no concept roll or comp selection required.

PREVIOUS REVIEW: The initial build review confirmed visual fidelity and scientific boundaries and requested
two fixes: a scoped `PRODUCT.md` and keyboard-accessible equation regions. Both
are resolved. The finish review's disposition is **ship** for these two fixes,
with no regressions observed in the supplied recaptures; this is not a deployment
readiness finding. This ordinary extension records its product context in
`PRODUCT.md` and continuity here.
Global `PRODUCT.md`, `DESIGN.md`, and `.impeccable/design.json` were already absent;
their absence is reported without creating a new system or repairing drift.

## Overview framing

The page and PDF say Project overview, with a short At a glance introduction
and a guided sequence from problem to solution to results, followed by human
oversight, governance, next steps, and reproducibility. The web contents rail
nests the four Case-result topics beneath Results. Replay and results actions
lead at the top; a native Downloads disclosure holds optional PDF/LaTeX files
at the bottom. `/research` and `/research/` redirect to `/overview/`.
Public `/overview/overview.pdf` and `/overview/overview.tex` map to the existing
`paper.pdf` and `paper.tex`, with `Antidote-overview` download filenames. The shared
mono typography, palette, Invert preference, equations, and evidence boundaries
are retained.

FINISH: The overview refinement received disposition **ship**, with no material
fixes. Its 1150×791 desktop, 390×844 mobile, and bottom-download captures passed.
The review sampled scientific framing and boundaries; it did not re-audit the
full study. Detector warnings were identified as known false positives or
preexisting findings.
