# Changelog

## 1.0.0 - 2026-11-13

First public release.

### Editor and building with Claude Code
- Browser editor with preview, timeline, scene, caption, voice, music and sound lanes, light and dark themes.
- Claude Code builds films as small, seekable HTML/SVG scenes. It proposes a scene list first and builds only after
  you approve it; your pinned values are never overwritten, only held for approval.
- Live chat panel with attachments, frame comments pinned to a moment, a working card that shows what Claude is doing
  (fed by Claude Code hooks), "Follow Claude" and "Attach frame".
- `moshfilm watch`, `propose`, `reply`, `say`, `status`, `plan`, `check` and `hooks` for the Claude side of the loop,
  plus a Claude Code skill (`skill/moshfilm`).

### Editing pack
- Undo and redo with a history list (survives reload, 100 steps or 20 MB), remove scenes, captions, voice lines and music,
  edit voice lines and captions in place.

### Shapes
- Main shape plus an optional second shape: 16:9, 9:16, 1:1 or 4:5, on one shared timeline and narration.
- `moshfilm check --layout` draws each scene in each shape and warns about overflow.

### Narration, music and sound
- Narration with Edge TTS voices, with fit checks that tell you when a line does not fit its scene.
- Generated music beds (moods, tempo, key, scale, palettes) and 12 sound-effect presets, synthesised locally with numpy.
  No audio files ship with the code. Preview and export play the same mix.

### Export
- MP4 or GIF with one file per shape, from the command line (`moshfilm export`) or the editor's **Export movie**
  button. Both write to the film's `exports/` folder.

### Security and packaging
- The editor listens on `127.0.0.1` only and rejects foreign hosts and origins.
- Files in the film folder are served with `X-Content-Type-Options: nosniff`; uploads in `sources/` are served as
  attachments; dotfiles and dot-folders are never served.
- Bundled sample film (`moshfilm sample`), `scripts/setup.sh`, MIT licence, third-party notices.
