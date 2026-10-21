# The Antidote

A presenter-led Caseathon research demo for harbor planners and invited judges. The working source is this GitHub checkout.

The main product view replays the supported March 2024 cargo/tanker arrival cohort in Hampton Roads. Default speed is 60 simulated seconds per real second; the month scrubber and traffic-window jumps make a full month practical to demonstrate. Three model tabs select the forecast attached to each vessel: frozen regression A, frozen XGBoost B, and degradation-aware XGBoost C (The Antidote).

Users change simulated report-delivery delay and position-error prevalence/offset, inspect the shared delivered feed, and compare actual fitted-model outputs. The guard can be disabled as an exploratory serving ablation; the learned model is never retrained by a control. Vessel trails and markers fade after the recorded analytical gate crossing. Expand the console for the product experience; select a vessel to inspect its data.

March contains training/development/previously inspected exploratory data. Live charts use common supported pre-crossing forecasts, equal approach weighting, and retrospective gate-crossing truth. They are not protected evaluation results. The protected April evaluation stays separately labeled and fixed. Arrival is an analytical gate proxy, not verified docking. Simulator labels never enter model features. Guard alerts are imperfect and do not constitute a calibrated operational policy.

Map motion interpolates between already delivered positions during playback. It can trail the latest report while completing a segment; model inputs, scores and the incoming feed retain their actual values. Pause freezes movement; seeking or changing faults resets the display to the requested snapshot. Reduced motion uses report-by-report positioning. The fleet console is the sole demo; the former single-vessel comparison is retired.

Preserve source integrity, fitted models, and all original calculations. Do not upload credentials, claim actual poisoning in NOAA data, or invent operator workload/safety/savings evidence.
