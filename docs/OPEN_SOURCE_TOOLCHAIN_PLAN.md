# Open-source toolchain audit and implementation plan

## Product goal

Build Mind of AK AI Studio as a personal, iPad-friendly creator workspace. Prefer self-hostable/open-source tools and avoid per-generation credit APIs. Keep the existing website as the product; prepare a PWA first and consider an Android wrapper later.

This document is an engineering plan, not a claim that the listed tools are already integrated. Each component must pass a licence, device-compatibility, resource, and functional test before being enabled.

## Reference products and feature-level study

Study publicly observable workflows and feature behavior from Adobe Premiere Pro, DaVinci Resolve, CapCut, and Runway. Reimplement general editing capabilities independently; do not copy proprietary code, private APIs, protected assets, or distinctive UI designs.

Feature areas to evaluate:
- Timeline editing: tracks, trim, split, reorder, transitions, audio levels, preview.
- Captions: transcript import, editable cues, subtitle styling, safe margins, SRT/VTT export.
- Audio: voiceover tracks, fades, ducking, volume, noise cleanup where feasible.
- Scene workflow: scene boundaries, thumbnails, shot selection, script-to-scene planning.
- Export: aspect ratios, resolution, quality presets, MP4 output and progress.

## Candidate open-source components

| Component | Intended role | Integration status | Key constraint |
|---|---|---|---|
| FFmpeg + FFprobe | Transcode, trim, mix, encode, inspect media | Already used by the current backend | Free-host CPU/RAM/time limits; sandbox every input and command |
| Whisper (open-source implementation) | Speech recognition and timestamped transcript | Not integrated | Model size and inference cost; Tamil-English accuracy must be tested |
| Piper | Local text-to-speech | Not integrated | Voice model licences vary; verify each model and Tamil availability |
| OpenCV | Frame sampling and computer-vision utilities | Not integrated | Not semantic understanding by itself |
| PySceneDetect | Scene-boundary detection alternative/evaluation | Not integrated | Compare speed and accuracy with current FFmpeg scene filter |
| wavesurfer.js | Audio waveform visualization in browser | Not integrated | UI component only; does not perform audio processing |
| Video.js | Browser video playback controls | Not integrated | Playback UI only, not a full editor |
| ComfyUI / Stable Diffusion ecosystem | Optional image-generation workflow | Not integrated | Heavy GPU requirement; model and checkpoint licences vary |
| MusicGen ecosystem | Optional original music experiments | Not integrated | Model licensing and compute must be checked before use; not a default production dependency |

## Recommended build order

### Phase 0 — Safety and foundations
1. Add owner-only access control before treating the hosted app as private.
2. Add a PWA manifest, install metadata, and a carefully scoped service worker.
3. Keep secrets in hosting environment variables; never commit passwords or tokens.
4. Add automated tests and document free-hosting limits.
5. Preserve the current working upload, validation, analysis, and export paths.

### Phase 1 — Captions
1. Review the existing `feat/free-caption-tools` branch and its tests.
2. Integrate script-to-SRT/VTT formatting only with explicit labelling that timing is approximate.
3. Add transcript import/editing and cue-level preview.
4. Add actual ASR only after a suitable inference location and Tamil-English tests are available.

### Phase 2 — Editing workspace
1. Build an iPad touch-friendly multi-track timeline UI.
2. Add trim/split/reorder and audio controls.
3. Translate timeline state into a validated FFmpeg render plan.
4. Test exported media with FFprobe and sample playback.

### Phase 3 — AI-assisted workflows
1. Scene summaries and script-to-scene plans.
2. Optional speech recognition and TTS integrations.
3. Optional image/visual generation only where licences and compute are acceptable.
4. Clearly distinguish deterministic tools from AI-generated suggestions.

### Phase 4 — Reliable personal library
1. Private project metadata and media storage.
2. Export history, cleanup, and backup/restore.
3. Background processing only when a suitable worker/storage arrangement exists.
4. PWA validation on iPad; Android packaging later.

## Current repository baseline

The current app is a FastAPI website with FFmpeg/FFprobe, upload validation, visual scene-change candidates, basic MP4 export, and script/SRT validation. The caption formatter branch exists separately and is not merged. The hosted Render Free service is not suitable for promising unlimited AI inference or long-form rendering. Temporary files may disappear on restart.

## Acceptance rules

- Never label a feature as complete until its route/UI and tests work.
- Never label approximate caption timing as speech-aligned transcription.
- Never claim semantic scene understanding from simple scene-change detection.
- Never promise unlimited free cloud compute or storage.
- Do not upload confidential personal media until owner-only access and private storage are implemented and verified.
- Keep changes on feature branches and use pull requests; do not merge or production-deploy without the owner's approval.
