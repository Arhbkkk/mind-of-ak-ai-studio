# Open-source editor research and integration decision

Research date: 2026-11-04

This document records a licence-aware review of public repositories for the Mind of AK AI Studio roadmap. It is an implementation decision record, not a claim that any external editor has been integrated.

## Short decision

Use **OpenReel Video** as the primary reference for the future browser editing experience. Its repository declares MIT, has a modular React/TypeScript monorepo, and documents multi-track video/audio/text/graphics editing, captions, transitions, keyframes, audio mixing, color tools, local autosave, export, and optional AI-assisted reversible edits.

Do not replace the current app with an unreviewed wholesale import. The current product is FastAPI + a single HTML/JavaScript frontend, deployed through a Cloudflare Worker and Render. OpenReel is a React/TypeScript/WebCodecs/WebGPU/Web Audio application. A safe integration requires a deliberate frontend migration or a separately built editor bundle, a documented media/project interchange schema, attribution, licence retention, and browser compatibility testing.

## Repository review

| Repository | Licence / status | Useful capabilities | Decision |
|---|---|---|---|
| [Augani/openreel-video](https://github.com/Augani/openreel-video) | MIT; active repository; latest observed update 2026-10-17 | Multi-track editing, captions, transitions, keyframes, audio mixing, color/effects, WebCodecs/WebGPU, MediaBunny, local autosave, optional AI editor | Primary architecture and feature reference. Port only the parts needed, preserve MIT notice for any copied code, and verify iPad Safari support before enabling browser-only features. |
| [opencut-app/OpenCut](https://github.com/opencut-app/OpenCut) | MIT; active rewrite, but README says it is being rebuilt | Rust/WebAssembly direction, browser/desktop/mobile aspirations, future editor API and plugin system | Monitor as a future option; rewrite is not a stable foundation to depend on today. |
| [opencut-app/opencut-classic](https://github.com/opencut-app/opencut-classic) | MIT; archived | Previous browser editor implementation | Useful for historical study only; archived status makes it a poor base for new production work. |
| [ffmpegwasm/ffmpeg.wasm](https://github.com/ffmpegwasm/ffmpeg.wasm) | MIT; active, README labels stability experimental | FFmpeg in browser through WebAssembly | Optional lightweight client-side fallback only. Do not make it the only renderer for long/high-resolution projects because browser memory, CPU and codec limits vary. |
| [thiagoalbrecht/weave](https://github.com/thiagoalbrecht/weave) | MIT; small browser editor | Converts a structured multi-layer composition document into an FFmpeg command | Useful architecture reference for one canonical timeline document driving both preview and export. |
| [openvideodev/react-video-editor](https://github.com/openvideodev/react-video-editor) | GitHub API returned NOASSERTION for licence | React editor, multi-track timeline, WebCodecs/PixiJS, R2/S3 storage integration | Do not copy or vendor until the repository's applicable licence is independently confirmed. |
| [Ektie/react-video-timeline-editor](https://github.com/Ektie/react-video-timeline-editor) | AGPL-3.0 | React multi-track timeline and editing interactions | Not selected. AGPL obligations need deliberate legal/licence review before incorporating it into this hosted application. |
| [etcyl/react-video-editor](https://github.com/etcyl/react-video-editor) | No licence declaration found in repository metadata during this review | React timeline, titles, transitions, ffmpeg.wasm export | Do not copy or vendor without an explicit licence. |

## Compatibility and product risks

1. OpenReel's README describes WebCodecs, WebGPU and browser-native rendering. Support and performance are browser/device dependent. iPad Safari must be tested directly; do not assume desktop Chrome compatibility transfers to iPad.
2. WebAssembly FFmpeg can run locally, but long 1080p/4K exports can exhaust browser memory or take too long. Retain the backend FFmpeg renderer as the dependable export path until measured tests prove a browser renderer is reliable for the target devices.
3. OpenReel's AI Editor expects the user to connect a provider/compatible endpoint. That is not a free built-in model. Keep AI optional, never expose provider keys in browser code, and do not silently consume paid credits.
4. A visual timeline and a backend renderer are not automatically equivalent. The same validated JSON composition must drive preview and render; tests must cover trims, gaps, overlaps, tracks, transitions, captions, audio and crop/framing.
5. Local browser autosave is not cloud backup. R2 project manifests and media objects need owner-scoped keys, signed access, cleanup boundaries and restore tests.
6. Licence and provenance metadata must be stored for imported media and generated assets. Do not scrape paid libraries or rehost assets without permission.

## Integration plan

### A. Keep the current service boundary
- Keep FastAPI for owner authentication, project APIs, upload sessions, render jobs and storage.
- Keep Cloudflare Worker as the public same-origin frontend/API proxy.
- Keep R2 for permanent project media, generated assets and exports; temporary uploads must remain in a separate lifecycle-managed prefix.
- Keep FFmpeg on the server as the authoritative renderer during the first editor integration.

### B. Introduce a canonical composition document
Version a JSON schema for:
- project metadata and channel profile;
- source media references and technical metadata;
- tracks (video, audio, image, text, caption, overlay, effect);
- clips with source in/out, timeline start, duration, transform, volume, speed and z-order;
- transitions, keyframes, subtitles, export settings and asset provenance.

Validate the schema server-side and reject unsupported features rather than silently ignoring them.

### C. Build the editor frontend in a separate, testable bundle
- Introduce a React/TypeScript/Vite editor workspace instead of growing the current monolithic HTML script indefinitely.
- Study OpenReel's component boundaries and interaction patterns; adapt only the pieces needed for the Studio.
- Preserve copyright and MIT licence notices for any code actually copied.
- Keep an accessible touch-first layout for iPad and keyboard/pointer controls for desktop.
- Feature-detect WebCodecs/WebGPU; offer a tested fallback rather than blank preview or false success.

### D. Make render parity a release gate
- Add golden composition fixtures and compare preview timing with rendered output.
- Test multi-source cuts, multiple video/audio tracks, still images, captions, overlays, fades, crossfades, audio ducking and crop modes.
- Verify output with FFprobe and automated audio/video checks.
- Run end-to-end tests on a real iPad Safari session before describing the editor as iPad-ready.

### E. Add AI only after deterministic editing works
- Start with script segmentation and transparent visual suggestions.
- Require the creator to approve external images/video and show provenance/licence.
- Treat AI edits as reversible operations against the composition document.
- Keep external model keys server-side and show provider/quota/cost requirements clearly.
- Do not mark a feature complete unless it has actually run and passed tests.

## Current repository gap analysis

The current main branch is still a small FastAPI/HTML application. Its public README says it has upload, media validation, scene-change candidates, basic MP4 export, SRT burn-in and a SQLite render queue. It does not yet have a full AI editor.

Existing draft PRs include:
- #18 owner-only access gate;
- #21 browser timeline foundation;
- #22 timeline export for up to 12 ranges from one source with hard cuts;
- #23 provider-neutral project storage foundation;
- #26 direct multipart uploads to R2.

These are foundations, not a finished production workflow. The current PR #22 timeline is not multi-source or multi-track, and its renderer does not implement transitions. PR #23 does not by itself provide a complete gallery/media workflow. PR #26 still requires the owner-auth and storage lifecycle work to be reviewed together.

## Acceptance gates

Do not call the product complete until all of these are demonstrated:
- owner authentication and same-origin protection work through the deployed Worker;
- projects can be created, saved, reopened, renamed and deleted after a server restart;
- source and generated media persist in private R2 storage;
- multi-track timeline changes are reflected in the actual rendered MP4;
- interrupted jobs can resume or report a precise failure;
- captions, audio, aspect ratios and exports are checked by automated tests;
- real iPad Safari upload, preview, edit, save and export tests pass;
- all copied dependencies and media assets have documented licences and provenance.

No merge or production deployment is implied by this research document.
