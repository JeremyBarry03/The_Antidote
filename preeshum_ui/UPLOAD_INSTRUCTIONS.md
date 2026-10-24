# Header-only upload for the new branch

Prepared specifically against `2026_WM_Hackathon-main 10`, your latest supplied GitHub repository.

## Upload to GitHub

1. Open your repository and select/create the new branch.
2. Go to the repository root and choose **Add file → Upload files**.
3. Drag the **Frontend folder inside preeshum_ui** into the upload area. Keep its folder structure.
4. Confirm that GitHub lists 9 files starting with `Frontend/tracking/`, then commit to the new branch.

Do not upload `preeshum_ui` as a parent folder, and do not flatten the individual files into the repository root. If you are already inside `Frontend/tracking/` on GitHub, return to the repository root before uploading this folder.

## Exactly what changes

- **1 existing file updated:** `Frontend/tracking/index.html`, taken from your supplied main 10 repository. Only a header stylesheet link, an independent module script, and the banner markup are added.
- **8 new files:** `header.css`, `header.mjs`, and the 6 files in `assets/antidote-ascii/`.
- The latest repository’s navigation, Overview link, replay, graphs, frontend app code, backend, models and data are preserved. No older `app.mjs`, `style.css` or `introduction.css` is included.
- Existing Geist Mono fonts and theme variables are reused; no installation or additional package is needed.
- Numbers and mathematical symbols use dark shading and bright highlights. Branches grow and retract; reduced-motion mode shows the completed sculpture.

The banner sits below the existing navigation and above the current replay tool. It uses its own scoped styles and entry point. Preview it through your normal local server or deployed site, not by opening index.html as a file.

Only upload the **Frontend** folder. This instruction file is for you and is not needed by the site.
