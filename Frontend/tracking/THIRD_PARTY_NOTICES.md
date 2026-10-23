# Arc UI component adaptations

`arc-components`, `arc-date-time`, and `arc-feedback` adapt the following free
Arc UI components published at https://uiarc.dev/:

- Foundation tokens: https://uiarc.dev/docs/theming
- Select: https://uiarc.dev/components/select
- Dropdown menu: https://uiarc.dev/components/dropdown-menu
- Button group: https://uiarc.dev/components/button-group
- Expandable card: https://uiarc.dev/components/expandable-card
- Tooltip: https://uiarc.dev/components/tooltip
- Dialog: https://uiarc.dev/components/dialog
- Button: https://uiarc.dev/components/button
- Floating button group: https://uiarc.dev/components/floating-button-group
- Icon morph: https://uiarc.dev/components/icon-morph
- Slider: https://uiarc.dev/components/slider
- Date picker: https://uiarc.dev/components/date-picker
- Calendar: https://uiarc.dev/components/calendar
- Time picker: https://uiarc.dev/components/time-picker
- Badge: https://uiarc.dev/components/badge
- Skeleton: https://uiarc.dev/components/skeleton
- Empty state: https://uiarc.dev/components/empty-state
- Alert: https://uiarc.dev/components/alert
- Scroll area: https://uiarc.dev/components/scroll-area

Unused original TSX/CSS reference copies are omitted from this UI-only
package. The full source handoff retains them in `tracking/vendor/uiarc/`.
The browser uses the native adapters shipped here. References were retrieved
from the site's public `/r/<component>.json` registry. Each registry
record marks these components as free. Arc UI documents the free source as MIT
licensed at https://uiarc.dev/docs/introduction#free-and-pro.

The live adapters use native browser controls and Web Animations rather than
React, Radix, or Motion. Rounded secondary buttons, their neutral surfaces and
hover/press feedback follow UIArc's free Button and Select component references.
The original dotted coastal map and requested Paradigm-style hairline sliders
remain in place. Adaptations and application code use the root MIT license.

## Geist Mono

Geist Mono is locally served from `assets/geist-mono-variable.ttf`.
The SIL Open Font License 1.1 is included in `assets/GeistMono-OFL.txt`.
Source: https://github.com/google/fonts/tree/main/ofl/geistmono .
This restores the earlier Paradigm-inspired typography; no proprietary Paradigm
font, branding, artwork, or source code is included.

## Mapbox GL JS

Version 3.32.0 is declared in `Frontend/package.json` and pinned in the lockfile.
The local server serves its installed distribution; no prototype folder is needed.
Mapbox's copyright, license, and terms are supplied by that npm package.
Map tiles retain Mapbox and OpenStreetMap attribution. A public Mapbox token and
network access are needed for the geographic basemap; the coordinate fallback is
available without a token.

## MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
