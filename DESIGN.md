---
name: "The Antidote"
description: "Harbor Shift Logbook: a paper-and-ink harbor research console."
colors:
  paper: "#f5f3ed"
  sheet: "#fffefa"
  ink: "#192e39"
  muted: "#54636a"
  rule: "#cdd1cc"
  teal: "#006d62"
  teal-light: "#e3eee6"
  red: "#b24437"
  red-light: "#fbeee8"
  a: "#96601b"
  b: "#446bb3"
  c: "#00776a"
  sea: "#102a35"
  subtle-surface: "#ecefe8"
  play-hover: "#00574e"
  tab-ink: "#4c6166"
  preset-ink: "#075f51"
  fault-ink: "#a1382c"
  fault-surface: "#fae9e2"
  map-a: "#e5bb75"
  map-b: "#8cb6f3"
  map-c: "#89d9bc"
  map-label: "#112d37ed"
  map-label-selected: "#163f45"
  map-text: "#ecf6ed"
  map-subtext: "#c6d9d1"
  response-surface: "#163e3c"
  response-text: "#e5f1e6"
  review-surface: "#4b3228"
  review-text: "#ffe8c5"
typography:
  display:
    fontFamily: "\"Avenir Next\", Avenir, \"Segoe UI\", sans-serif"
    fontSize: "58px"
    fontWeight: 650
    lineHeight: 1.05
    letterSpacing: "-0.04em"
  headline:
    fontFamily: "\"Avenir Next\", Avenir, \"Segoe UI\", sans-serif"
    fontSize: "25px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  research-headline:
    fontFamily: "\"Avenir Next\", Avenir, \"Segoe UI\", sans-serif"
    fontSize: "30px"
    fontWeight: 550
    lineHeight: 1.2
    letterSpacing: "-0.03em"
  body:
    fontFamily: "\"Avenir Next\", Avenir, \"Segoe UI\", sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  supporting:
    fontFamily: "\"Avenir Next\", Avenir, \"Segoe UI\", sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.6
  label:
    fontFamily: "\"Avenir Next\", Avenir, \"Segoe UI\", sans-serif"
    fontSize: "12px"
    fontWeight: 600
  tab:
    fontFamily: "\"Avenir Next\", Avenir, \"Segoe UI\", sans-serif"
    fontSize: "14px"
    fontWeight: 600
  metric:
    fontFamily: "\"Avenir Next\", Avenir, \"Segoe UI\", sans-serif"
    fontSize: "37px"
    fontWeight: 550
    lineHeight: 1
    letterSpacing: "-0.03em"
  clock:
    fontFamily: "\"Avenir Next\", Avenir, \"Segoe UI\", sans-serif"
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1
    letterSpacing: "-0.02em"
  map-eta:
    fontFamily: "\"Avenir Next\", Avenir, \"Segoe UI\", sans-serif"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "-0.01em"
rounded:
  square: "0"
  micro: "2px"
  code: "3px"
  label: "4px"
  control: "5px"
  console-mobile: "6px"
  console: "8px"
  round: "50%"
spacing:
  "2": "2px"
  "4": "4px"
  "8": "8px"
  "12": "12px"
  "16": "16px"
  "20": "20px"
  "24": "24px"
  "28": "28px"
  "44": "44px"
components:
  play-control:
    backgroundColor: "{colors.teal}"
    textColor: "#ffffff"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "8px 13px"
  play-control-hover:
    backgroundColor: "{colors.play-hover}"
  icon-control:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px"
    size: "35px"
  text-control:
    backgroundColor: "transparent"
    textColor: "{colors.teal}"
    padding: "7px 0"
  model-tab:
    backgroundColor: "transparent"
    textColor: "{colors.tab-ink}"
    typography: "{typography.tab}"
    rounded: "{rounded.square}"
    padding: "14px 24px"
  model-tab-selected:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.teal}"
  fault-range:
    height: "5px"
    width: "100%"
  condition-preset:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "5px 8px"
  condition-preset-selected:
    backgroundColor: "{colors.teal-light}"
    textColor: "{colors.preset-ink}"
  vessel-row:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.code}"
    padding: "8px 9px"
  vessel-row-selected:
    backgroundColor: "{colors.teal-light}"
  response-banner:
    backgroundColor: "{colors.response-surface}"
    textColor: "{colors.response-text}"
    padding: "13px 22px"
  response-banner-review:
    backgroundColor: "{colors.review-surface}"
    textColor: "{colors.review-text}"
  comparison-card:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    padding: "14px 0 0"
  map-marker-label:
    backgroundColor: "{colors.map-label}"
    textColor: "{colors.map-text}"
    rounded: "{rounded.label}"
    padding: "8px 10px"
    width: "150px"
  map-marker-label-selected:
    backgroundColor: "{colors.map-label-selected}"
---

# Design System: The Antidote

## Overview

**Creative North Star: "Harbor Shift Logbook"**

Harbor Shift Logbook is a practical traffic console with a warm paper shell, measured sans typography, flat ruled groups, and a dark geographic chart. The identity comes from careful alignment, readable numbers, and restrained color. It has no simulated aging, decorative shoreline illustration, or ornamental motion.

The shell supports a presenter inspecting evidence. Controls, forecasts, delivered messages, and explanatory notes must remain legible together. Clear labels and source limits carry the meaning; visual status must never imply more certainty than the underlying research supports.

**Key Characteristics:**

- Warm paper and ink surrounding a dark harbor chart.
- A familiar sans family with tabular numeric readouts.
- Teal action and Antidote response; separate model and annotation colors.
- Flat groups divided by rules, with compact native controls.
- Restrained transitions that follow user action and the replay clock.

The frontmatter is the normative token layer. It describes the finished fleet replay in `Frontend/eta_replay.html` and `Frontend/replay/fleet.css`, with map and chart colors from the corresponding fleet modules. The extension sidecar records observed behavior and representative snippets. It is documentation of this implementation, not a replacement stylesheet.

## Colors

The palette combines warm neutral surfaces and blue-black ink with practical, meaning-bearing accents. Token values above are authoritative; metadata ramps in the sidecar are non-normative previews.

### Primary

- **Harbor Teal** (`teal`) marks primary action, focus, controls, links, selected model tabs, and Antidote identity.
- **Teal Wash** (`teal-light`) marks selected vessels and condition presets without adding elevation.
- **Deep Teal** (`play-hover`) is the play control's observed hover state.
- **Antidote Series** (`c`) draws C in the comparison charts. The brighter **Map Antidote** (`map-c`) is its dark-chart equivalent; do not exchange the two contexts.

### Secondary

- **Regression Ochre** (`a`) and **XGBoost Blue** (`b`) identify A and B in light-background charts.
- **Map Ochre** (`map-a`) and **Map Blue** (`map-b`) identify the same models against the dark chart. Map Ochre also marks the analytical crossing reference; the legend states its role.

### Tertiary

- **Simulation Red** (`red`, `red-light`, `fault-ink`, `fault-surface`) supports service errors and known altered-field annotations. The field annotation pair is distinct from the global error-banner pair.
- **Response Teal** (`response-surface`, `response-text`) carries C's clear and handled states. **Review Umber** (`review-surface`, `review-text`) carries a provisional request for human review. The associated symbol, title, and copy change with state.

### Neutral

- **Warm Paper** (`paper`) is the page; **Clean Sheet** (`sheet`) is the bounded console and native controls.
- **Harbor Ink** (`ink`) is the main text; **Measured Gray** (`muted`) supports notes and labels; **Rule Gray** (`rule`) separates groups.
- **Subtle Surface** (`subtle-surface`) is shared by the toolbar and plot panels. `tab-ink` and `preset-ink` retain their actual control-specific text treatments.
- **Night Water** (`sea`) is the map base. `map-label`, `map-label-selected`, `map-text`, and `map-subtext` keep floating forecast labels readable over geography.

**The Meaning Before Color Rule.** Pair every model, condition, and warning color with a code, label, symbol, or explanatory text. Red field annotations mean known simulated changes for the audience; they do not mean the model detected a fault.

## Typography

**Display and body family:** Avenir Next, with Avenir, Segoe UI, and generic sans-serif fallbacks. The implementation uses the local stack and does not load a remote font. There is no separate decorative or monospaced family.

The scale is measured rather than based on a single mathematical ratio. The large title leads into compact evidence; chart values and the replay clock receive their own numeric emphasis. Weight and tracking establish hierarchy without uppercase body copy.

### Hierarchy

- **Display:** the page title; `display` is the desktop role. It becomes 48px at the 860px breakpoint and 43px at the 650px breakpoint.
- **Headline:** main section headings use `headline`. The closing research heading uses `research-headline` and becomes 27px on narrow screens.
- **Body:** `body` describes the introduction explanation. Its line length is capped at 78ch in the final stylesheet; narrow layouts use the same measure within the available width.
- **Supporting:** `supporting` describes chart footnotes and scoring notes. Final overrides raise report/table text, fault descriptions, and control supporting text to 12px, and research detail paragraphs to 13px.
- **Label and tab:** `label` and `tab` retain the control hierarchy. Archive tags, report metadata, and vessel facts use smaller contextual labels; several become 10px on narrow screens.
- **Metric, clock, and map ETA:** `metric`, `clock`, and `map-eta` emphasize numeric information. Metrics become 31px at the 860px breakpoint and 36px at the 650px breakpoint; the clock becomes 18px on narrow screens, and map ETA becomes 13px.

Time, output, metric, report, vessel-fact, and ship-label elements use tabular figures. Normal sentences remain proportional.

**The Shared Clock Rule.** Keep time, units, and retrospective scoring labels visible beside the evidence they describe. An unavailable value is shown as an em dash or an explicit unavailable state.

## Layout

The page is centered within a maximum width of 1640px, with 44px side padding on wide screens. The console is the main bounded surface. Its toolbar spans the map and incoming-feed panel; playback and fault controls continue beneath. The map column and feed stretch together, allowing the chart height to grow with the feed rather than clipping content.

The map/feed grid uses a flexible chart column and a 346px feed. At the 1150px breakpoint, page padding becomes 28px and the feed becomes 300px. At 860px it becomes 275px; playback wraps, the month timeline takes a full row, and mitigation moves beneath the two fault inputs. At 650px, page padding becomes 16px, map and feed stack, fault controls become one column, and the three charts stack. The vessel list becomes a horizontal scroller, vessel facts remain a two-column grid, and message rows have bounded vertical scrolling. A third header section link and secondary map legend text are hidden at this width; the corresponding sections remain in the page.

The final map minimum is 480px on wider screens and 400px at 650px and below. The chart viewport scales with its column; line plots retain a 126px height, becoming 130px on narrow screens. Ruled sections use varied but consistent observed spacing steps recorded in frontmatter; these are extracted steps, not an assertion that every gap is one scale increment.

Expanded product view fills the viewport and scrolls vertically. It removes the outer console border and radius. Its wide map height is `max(400px, calc(100dvh - 390px))`, subject to the final map minimum; on narrow screens it uses `54dvh` with the same final narrow minimum. Escape exits the expanded class-based view. The fullscreen control updates its accessible label and expanded state.

## Elevation & Depth

The document surface is flat. One-pixel rules, dark/light contrast, and modest background shifts establish grouping. Model selection uses an inset teal rule. Known altered fields use a tight same-color spread to retain a continuous highlight. Neither is a floating shadow. Over the map, a small label shadow and hull drop shadow separate live evidence from geography; these are the only floating depth vocabulary recorded in the sidecar.

**The Ruled Surface Rule.** Separate ordinary content with borders, alignment, and tonal surfaces. Reserve floating shadows for vessel labels and hulls over the map.

Motion follows the replay clock: vessel hulls and headings interpolate along already delivered reports at animation-frame frequency, with trail uploads bounded to 10 Hz. The display can trail the latest report while completing a segment; it never extrapolates future positions or changes predictor inputs. Pause freezes motion, while seeking or changing faults snaps to the requested snapshot. Reduced motion uses report-by-report positions. Button/link color changes use short ease-out transitions, and vessel/trail opacity follows eight simulated minutes after the recorded crossing. The explicit inspect-vessel action still requests smooth scrolling in JavaScript; this is an observed implementation limit, not a broader accessibility guarantee.

## Shapes

Ordinary controls have gently softened corners, compact model-code boxes are tighter, and tabs remain square. The console has a larger enclosing radius that reduces on narrow screens. Forecast labels use a small corner radius, while status dots and the response symbol are circular. Rounded values in frontmatter describe these specific roles; they are not a license to turn the flat ruled groups into cards.

Icons are small inline, unfilled stroke drawings with rounded caps and joins. Play/pause uses filled geometry. The vessel hull has a filled directional silhouette. The map connector may move a label to avoid overlap while the hull stays anchored to the reported coordinate.

## Components

### Playback and compact actions

The play/pause control is the sole filled light-surface action. It pairs icon and text and retains its width across state changes. Expand is a compact outlined icon button with an accessible name; reset is an underlined text action. Base buttons use a sheet surface and rule border, with a subtle hover wash. Disabled buttons, inputs, and selects are half opacity with a waiting cursor. The source defines hover and focus treatments but no special pressed animation.

### Model navigation

Three semantic tabs select the forecast displayed on the shared map. Selected tabs have a sheet background, teal text, and an inset lower rule; all retain the model code. Arrow keys, Home, and End update selection and focus. Only the selected tab remains in the tab order, and the workspace is labeled by that tab. The shield icon accompanies C and hides on narrow screens. The response banner is visible only for C.

### Fault inputs and condition presets

The fault controls are native range inputs, labeled with live output and end labels. A native select chooses the position offset, and a native checkbox controls the input guard. Range controls inherit teal accent and maintain their thin track. The guard remains an ordinary checkbox rather than a fabricated switch. Presets are small outlined buttons with `aria-pressed`; their selected state uses Teal Wash. Reset and all presets change the condition without implying model retraining.

### Vessel rows and delivered messages

A selectable vessel row pairs a dot, truncated name, and ETA or explicit unavailable/crossed state. `aria-pressed` and a wash identify selection. The detail group presents labeled facts and a semantic table presents observed time, position, and speed. Red altered fields include explanatory text or an original-position title; the feed key states that the marks are known simulated changes. Preserve empty and unavailable messages rather than fabricating a numeric reading.

### Response banner

The C banner combines an outlined circular symbol with a title, explanation, and a conditional inspect action. Clear, handled, and review states are distinct textual states; review changes to umber and an exclamation mark. It reports observable freshness/consistency checks and provisional review needs. A clear state explicitly allows that a forecast can still be wrong. It is a status region, not a calibrated operational acceptance policy.

### Comparison panels and research disclosures

Each chart panel begins with a thin model-colored top rule, a model code and name, a large metric with unit, sample count, inline SVG plot, coverage row, and a methodology footnote. The panels are flat and border separated. Missing metrics use an em dash. Use the real fitted-model outputs: common supported pre-crossing cases, equal weighting by approach, retrospective crossing truth, and visible coverage. MAE and RMSE use minutes; MSE uses squared minutes. The protected April results remain fixed in a separately labeled native disclosure. Research notes use native `details` and `summary` with ruled separators.

### Vessel map labels and coordinate fallback

A map marker is a button comprising hull, connector, and forecast label. Selection changes label border/surface; a large retrospective error changes the secondary text color. Labels may be repositioned to reduce overlap while the geographic point stays fixed. Trails show delivered positions and fade with the crossing state. Geographic rendering uses the dark Mapbox style with attribution. If it cannot load, the latitude/longitude plot retains the actual positions, labels, tracks, and analytical gate, with an explicit basemap-unavailable label; it does not invent geography.

All interactive elements preserve the visible teal focus outline (3px with 4px offset). A skip link appears on focus, native controls keep their labels, and dynamic loading/error/response regions carry their existing status or alert roles. These are observed affordances, not a claim of a complete accessibility audit. The sidecar's ten examples are static, self-contained render samples of actual components; application state and calculations remain in the source modules.

## Do's and Don'ts

### Do:

- **Do** preserve the warm paper, ink, and dark chart relationship.
- **Do** keep controls native, labeled, and visibly focusable.
- **Do** use tabular numbers for time, outputs, metrics, reports, vessel facts, and map labels.
- **Do** preserve selected, unavailable, loading, quiet-window, review, and error states with explicit text.
- **Do** keep explanatory footnotes attached to charts and the protected evaluation clearly separate from interactive results.
- **Do** let narrow layouts stack the console and charts while retaining the same evidence and units.

### Don't:

- **Don't** add faux aged paper, illustrative geography, or decorative motion.
- **Don't** turn every section into a raised or rounded card.
- **Don't** use red simulated annotations as a detection-success claim or treat a clear guard state as proof that a forecast is correct.
- **Don't** fill empty metrics with invented values or score missing forecasts as zero error.
- **Don't** replace the coordinate fallback with an imitation basemap or omit its unavailability label.
- **Don't** describe the analytical gate as verified docking or the March replay as protected evaluation evidence.
