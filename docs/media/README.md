# Application media provenance

The original JPG screenshots and playback clip were captured October 28, 2026 from `https://theantidote.netlify.app/`. The additional PNG results and opening dashboard views, and the application walkthrough recording, were supplied by the user on the same date; their capture URLs were not independently verified. The repository source remained at commit `766af7246141408870e7b63bc7e8394422892942` before documentation edits; no deployed commit was independently established from the hosting account.

| File | Capture context |
| --- | --- |
| `dashboard-hero.png` | User-provided opening screenshot, copied without modification; BLUE ONE and MSC ANSHIKA VI, replay clock 05:33:36 UTC, all disruption controls at zero |
| `app-walkthrough.mp4` | User-provided `Screen Recording 2026-10-28 132840.mp4`, copied without modification; replaces the second screenshot in the README with a video link |
| `app-walkthrough.gif` | Animated preview of the complete supplied recording, resized to 1,000 pixels wide at 8 frames per second with a 64-color palette; the README preview links to the unchanged full MP4 |
| `miranda-disruption.png` | User-provided screenshot, copied without modification; third visual in the README after the opening screenshot and recording; MIRANDA at March 13, 00:36:31 UTC; simulated reporting gap 33 min, missing course 32%, sensor drift 54%, location drift 15%, sensor deterioration 18%; remaining controls zero |
| `illustrated-results.png` | User-provided screenshot, copied without modification; missing course, sensor drift, location drift, and sensor deterioration selected at 25%; March 15 illustrated cutover; added-error summaries Poly +1.6 min, XGBoost +1.9 min, Antidote +0.7 min; Poly hidden only in the daily-error panel |

Screenshots preserve the actual interface, including Mapbox/OpenStreetMap attribution and the Netlify badge. The video adds even-width padding for codec compatibility and no overlays. It shows an observed UI replay, not a fresh model evaluation. The screenshot/clip clocks show historical replay time, not the capture date.

The saved April combination experiment figure remains under its original `Data_Science/experiments/` path and has its own protocol. It is independent of these app captures and of the nominal March benchmark.

The README's illustrated added-error table transcribes the three rounded labels visible in `illustrated-results.png`. The full curves were not digitized, and no missing values were inferred. All values in this screenshot are illustrative, rather than measured benchmark results.
