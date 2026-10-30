# Creator Channel Profiles and Production Requirements

Mind of AK AI Studio is a private, owner-operated, online-first creator production workspace. It serves three distinct channel workflows through one shared project, asset, editing, rendering, and gallery backend.

## Creator profiles

### 1. Mind of AK
- Content: science, technology, human biology, discoveries, business explainers, mysteries, research-led documentaries and educational Shorts.
- Typical video duration: 30 seconds to 8 minutes.
- Primary formats: 9:16 and 16:9; also support 1:1 and custom ratios.
- Editorial direction: curiosity-led opening, clear explanatory structure, credible source handling, documentary visuals, readable captions, natural narration and restrained sound design.
- Language: Tamil/Thanglish and English, including mixed-language scripts.
- Editing automation: parse script and supplied SRT, map sentences to scenes, inspect supplied images/video, propose or generate missing visuals where available, compose captions inside safe areas, select music/SFX by mood, build a reviewable timeline and render.

### 2. Kids Stories
- Content: original child-friendly animated stories and educational storytelling.
- Long-form target: 15 minutes or longer where needed; generate in resumable parts and assemble into one continuous project.
- Requirements: persistent character identity sheets, consistent voices, locations, wardrobe and visual style; scene-by-scene generation; narration and optional character dialogue; age-appropriate music and natural SFX; continuity checks between parts.
- Every generated part must retain its script, assets, voice settings, scene plan and generation status so a project can resume after interruption.

### 3. Mind Relax BGM
- Content: relaxing music, original melodies, rain and nature ambience, sleep and meditation soundscapes.
- Requirements: prompt-driven mood and sound design; support instrumental music, ambience and natural environmental audio; seamless looping where requested; long-form audio/video assembly; loudness and transition checks.
- Respect source and model licences. Do not claim a generated track is original or commercially cleared unless the model/source terms support that claim.

## Shared production workflow

1. Create or open a project and choose a creator profile.
2. Accept script, SRT, video, images, audio, reference media and written instructions in any useful combination.
3. Analyze assets and media metadata; preserve original uploads.
4. Parse script into beats, scenes and shot requirements.
5. Produce an editable scene plan with explicit asset provenance and confidence.
6. Select licensed library assets or generate missing assets using available models/providers.
7. Create or import narration, subtitles, music and sound effects.
8. Automatically compose the timeline, including crop, safe areas, text placement, transitions and audio mixing.
9. Preview the actual edit and allow manual corrections.
10. Run quality checks for script/visual alignment, continuity, subtitle timing, audio clipping, black frames, aspect ratio, safe areas and render integrity.
11. Render online in background jobs, with progress, retry and cancellation.
12. Save project state and deliverables to persistent owner-only gallery.

## Format and duration requirements

- Standard editing projects: 30 seconds to 8 minutes.
- Kids story projects: support 15 minutes and longer through chunked, resumable generation and rendering.
- Primary aspect ratios: 9:16 and 16:9; secondary: 1:1 and configurable custom dimensions.
- Composition must be content-aware. Never stretch source visuals to fit; use subject-aware crop/reframe, background extension/blur only when appropriate, and safe placement for captions and graphics.

## Asset library requirements

Build a reusable, searchable online library for transitions, film burns, overlays, SFX, ambience, music, fonts, backgrounds and templates. Store source URL, creator, licence, attribution, permitted use, retrieval date, checksum and local storage reference. Only download/cache assets when source terms permit it. If a source prohibits mirroring or automated access, use its permitted embed/API/link workflow instead.

## Online architecture requirements

- All user-facing workflows must work in a browser on iPad, Android and desktop.
- Use persistent object storage for uploads, generated media, project files and exports; temporary container storage is not a project gallery.
- Use a database for projects, assets, jobs, channel profiles and generation history.
- Use background workers and resumable jobs for transcription, generation and rendering.
- Keep secrets server-side; isolate all project and media routes behind owner authentication.
- Prefer open-source/local/self-hostable components and no per-use paid API dependency, but disclose that hosted compute, storage, bandwidth and third-party generation services may have quotas or costs.
- Never describe unlimited free online AI generation or rendering as guaranteed.
- Keep current live production unchanged until the owner approves a PR merge and deployment.

## Product truth and implementation discipline

The current app does not yet implement this complete workflow. Each feature must be marked as planned, implemented, or tested. Do not present a mock UI or edit brief as a functioning AI pipeline. The actual timeline must drive the final render. Generated content must be previewable and editable before export.
