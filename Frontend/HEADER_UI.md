# Antidote header UI

Preeshum's header is integrated into Netlify's published Frontend/tracking/
directory. There is no separate preeshum_ui wrapper folder.

- tracking/index.html contains the banner markup and loads header.css and header.mjs.
- tracking/header.css scopes the banner styles to #antidote-header.
- tracking/header.mjs mounts the artwork independently of the replay and graphs.
- tracking/assets/antidote-ascii/ contains the six animation modules.

The header uses existing Geist Mono fonts and theme variables. No extra packages,
build commands, backend changes, model changes or data downloads are required.
Reduced-motion mode shows the completed artwork.

Netlify already uses Frontend as its base and tracking as its publish directory.
Commit and push these integrated files through the normal deployment workflow to
publish them. Preview through the normal local server rather than opening the
HTML file directly.
