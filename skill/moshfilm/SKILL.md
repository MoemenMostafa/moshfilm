---
name: moshfilm
description: Use when the person wants to make or change a short motion-graphics film with moshFilm, or when a moshFilm chat message or frame comment arrives
---

# moshFilm

moshFilm turns a topic, script or document into a short motion-graphics film. The person works in a browser editor
(preview, timeline, comments, a chat panel); you write the scenes and answer through the `moshfilm` command line.
You never talk to the person in the terminal about the film: you answer in moshFilm's chat panel, and they talk to you there.

All commands below take the film folder (the folder that holds `film.json`) as `<folder>`.

## 1. Start

1. Run `moshfilm --version`. If the command is not found, tell the person to run `scripts/setup.sh` in the moshFilm
   checkout (it puts `moshfilm` on PATH) and stop.
2. Start the editor in the background unless it is already running: `moshfilm open <folder>`. It serves on
   `127.0.0.1` (first free port from 5717 to 5727), prints the address, and creates the folder if it is new.
3. Connect with `moshfilm watch <folder>`, run with the Monitor tool (or any background process you can read).
   It prints one JSON line per chat message, frame comment or event (a chat line may carry an `attachment`, the path of
   a file the person uploaded into `sources/`; read it), and writes the heartbeat that makes the panel show
   "Claude connected". Keep it running for the whole session; if it dies, restart it.
4. No Monitor tool: run `moshfilm watch <folder> --once` as a background command. It exits after the first batch of
   lines; read them, act, then start it again. The panel shows "Claude connected" only while a watch is running, so
   restart it right after each batch.

5. The panel's working card (spinner, elapsed time, your steps) is fed by Claude Code hooks that `moshfilm new` and
   `moshfilm sample` install into `<folder>/.claude/settings.local.json`. For a film made earlier, the person runs
   `moshfilm hooks install <folder>` once. A Claude session reads hooks only when it starts, so they take effect after
   the session restarts; you cannot enable them from inside a running session. You do not call `moshfilm activity`
   yourself (the hooks do).

## 2. Folder rules

- Never edit `film.json`, `comments.json` or `proposals.json` by hand. The server owns them.
- Write `scenes/<id>.js` directly; that is the only file you create by hand (plus anything the person puts in
  `sources/` or `music/`, which you only read).
- Every other change (adding, removing or reordering scenes, titles, lengths, voice lines, text clips, status) goes
  through a proposal: write JSON, then `moshfilm propose <folder> <file.json>` (use `-` instead of the file to read
  standard input). Shape: `{"summary": "...", "needs_approval": false, "changes": [...]}` with changes
  `add_scene`, `remove_scene`, `move_scene`, `set_scene`, `set_voice`, `add_text`, `set_text`, `remove_text`, and for
  sound `add_sfx`, `set_sfx`, `remove_sfx`, `set_music` (section 6b).
- Pinned timing is the person's. When they drag a scene length, a text clip, a voice line or the scene order in the
  timeline, that value becomes pinned and your proposals never overwrite it: the pinned part is held and shown to the
  person to approve. To change a pinned value, ask in chat first, then send the proposal; it waits for their approval.
- Words the person typed are theirs too. When they edit a voice line or a caption in the timeline (double-click),
  that text is pinned (`text_pinned`) and your proposals never overwrite it: a `set_voice` with `text`, or a `set_text`
  with `text`, onto pinned words is held for the person to approve (a `remove_text` or `remove_scene` that would
  delete them is held too). Their other fields still apply. To change pinned words, ask in chat first. An `event` line
  "The person edited the narration of scene ..." or "... edited the caption ..." tells you it happened; the voice is
  re-made by the editor itself, so do not run `moshfilm voice` for it.
- Things the person removed stay removed. When they delete a scene (with its voice line and captions), a caption, a
  voice line, a sound effect or the music, the film records it (`removed_by_person`) and you get an `event` line such as "The person
  removed scene 03 ...". Never add it back on your own: an `add_scene`, `add_text`, `add_sfx`, `set_music` or `set_voice` that would bring it
  (or the same title or words under a new id) back is held for their approval, and changes to a removed scene or text
  are ignored. If you think it is needed, say so in chat and let them decide.
- Undo and redo cover `film.json` and the top-level `scenes/*.js` files only. Other files you write (helper folders,
  `sources/`, `music/`) are not snapshotted, so an undo never restores or deletes them.
- The person can undo and redo, and one of your turns is one undo step ("Claude: edited scene 03"). After an `event`
  line "The person undid: ..." (or redid, or jumped to a step), `film.json` and your scene files may have changed under
  you: read them again before editing, and do not rewrite something they just undid unless they ask.
- A proposal with `"needs_approval": true` also waits. Do not build on it until an `event` line says it was approved.

## 3. Starting a film

When the person gives a topic, a script, or a document (look in `sources/` for uploads):

1. Read it. Pick one idea per scene.
2. Propose the scene list: one `add_scene` per scene with `id` (`s1`, `s2`, ...), `title`, a short voice `text`, a rough
   `length` in seconds, and `status: "planned"`. Set `"needs_approval": true`. See `examples/example-proposal.json`.
3. Send a one-line summary with `moshfilm say <folder> "Proposed 6 scenes: ... Approve in the panel to start building."`.
4. Wait for the `event` line saying the proposal was approved. If it was rejected, ask what to change in chat and propose again.

## 4. Build loop

Per scene N of M, in film order:

1. Tick the plan step for this scene (`moshfilm plan <folder> --done N`), or `moshfilm status <folder> "building scene N of M"`.
2. Propose `{"op": "set_scene", "id": "s1", "status": "building"}` (the preview shows a "Building" card).
3. Write `scenes/s1.js` (rules in section 6).
4. Propose `{"op": "set_scene", "id": "s1", "file": "scenes/s1.js", "status": "ready"}` plus `add_text` clips for on-screen
   captions, then run `moshfilm check <folder> --layout` and fix every error and warning it prints. It draws the scene
   in each of the film's shapes; a `[9:16] ... sticks out of the frame` warning means the scene is not responsive, so
   fix the scene (section 6), not the shape.

After the last scene:

1. Run `moshfilm voice <folder>`. It makes the narration and prints, per scene, the voice length against the scene length.
   A line marked `voice doesn't fit — stretch scene or shorten line` must be fixed: shorten the line with a `set_voice`
   proposal, or ask the person (a pinned length is theirs) whether to stretch the scene. Never leave a scene shorter than
   its voice line.
2. `moshfilm status <folder> --clear`, then `moshfilm say <folder> "All N scenes are ready. Press play."`.

## 5. Handling a line from watch

Each line is JSON with `id`, `kind` and `text`:

- `chat`: the person wrote to you; an `attachment` field names a file they uploaded (under `sources/`), so read it
  first. An `at` field (`{"time", "scene", "sceneTitle"}`) means they pointed at a frame: `time` is seconds in the whole
  film and `scene` is the scene there. Treat it exactly like a frame comment's `time` and `scene`: look at that scene at
  that moment, and change just that part when they ask for a change. Answer with `moshfilm reply <folder> <id> "<text>"` (this also resolves the item).
  Do the work they asked for first when it is quick. For any request with several steps, set a plan (section 5a).
- `comment`: a note pinned to a frame. It carries `time` (seconds in the whole film), `scene` (scene id), `scene_time`
  (seconds into that scene) and `point` (`x`, `y` from 0 to 1, measured from the top-left of the frame). `aspect` and
  `frame` (`{"width", "height"}` in pixels) say which shape the person was looking at and how big its frame is: `point`
  is a fraction of that frame, so look at the scene drawn in that shape. Look at that
  scene at that moment, change just that part of that scene, then `moshfilm reply <folder> <id> "<what you changed>"`;
  the reply resolves the comment. `moshfilm resolve <folder> <id>` resolves without a reply; add `--keep-open` to
  `moshfilm reply` when you answered a question but the item should stay open.
- `event`: something happened that you did not do. Act on approvals (continue building), rejections (ask what to change)
  and invalid proposals (read the message, fix the JSON, propose again).
  An event "Proposal pN: the person kept their pinned values; its other changes were applied" is not a rejection:
  only the held (pinned) changes were declined, so keep building on what was applied.

### 5a. Plan checklist

For any multi-step request, set a plan first and tick items off as you go; the panel shows it at the top of the
working card and ticks it live:

- `moshfilm plan <folder> --set "Outline the scenes" "Build scene 1" "Check and fix"`: replace the plan.
- `moshfilm plan <folder> --done 2`: tick step 2 (1-based) when it is finished, not before.
- `moshfilm plan <folder> --clear`: remove the plan when the whole request is done.

Keep step texts short and plain. `moshfilm status` still works for a one-line progress note, but the working card
already shows what you are doing, so use a plan instead for anything longer than a moment.

Several lines can arrive together; handle them in order. Never answer in the terminal what belongs in the panel.

## 6. Scene-writing rules

A scene is an ES module in `scenes/<id>.js`. Its default export is exactly:

```js
export default {
  setup(root, ctx) { /* build all DOM/SVG inside root, once */ },
  render(t, ctx) { /* set styles and attributes for time t */ },
};
```

`root` is an empty element that fills the stage. `ctx` is `{width, height, length, random}`: the size in pixels of the
shape being drawn, the scene length in seconds, and a seeded random function.

`ctx.width` and `ctx.height` differ between shapes (by default 1280 by 720 for 16:9, 720 by 1280 for 9:16, 720 by 720
for 1:1, 720 by 900 for 4:5; the short side stays the same). Never write fixed pixel positions: place things as
fractions of `ctx.width` / `ctx.height`, size type from `Math.min(ctx.width, ctx.height)`, and switch the arrangement
with `const portrait = ctx.height > ctx.width` (stack in a column, wrap a row into two). `setup` runs again whenever
the size changes (the person picks another shape, or the second shape is previewed), so build from `ctx` there and
keep nothing sized at module level. See `examples/example-scene.js`.

- `render` is a pure function of `t` (seconds from the scene start, from 0 to `ctx.length`). The player calls it in any
  order, backwards and repeatedly, and the export calls it once per frame, so the same `t` must always give the same picture.
  Build every element in `setup`; in `render` only set styles and attributes (and text content that depends on `t`).
- Deterministic only: no `Math.random`, `Date.now`, `new Date`, `performance.now`, `setTimeout`, `setInterval` or `requestAnimationFrame`
  (`moshfilm check` warns about them). For randomness use `ctx.random()`; it is re-seeded before every `render` call.
- Draw with DOM, SVG and CSS. Lay out in the `ctx.width` by `ctx.height` stage with absolute positions computed from
  `ctx`. Use the system font stack (`system-ui, sans-serif`); no network assets, no external libraries.
- Ease with small helpers defined in the file (`clamp`, `lerp`, `easeInOut`), as in `examples/example-scene.js`.
- Keep the scene's main idea readable for its whole length; do not clear the screen before the voice line ends.
- Leave on-screen captions to text clips (`add_text`) unless the text is part of the drawing.
- Scenes may import a relative helper module (for example `./lockers.js`). Changes to a helper reach the preview only
  after a full reload of the editor page; changes to a scene file reload on their own.

## 6a. Shapes

- The film has a main shape (16:9, 9:16, 1:1 or 4:5) and optionally a second one; both share the one timeline and the
  one narration. The person picks them in the editor ("Shape" and "Second" in the timeline header). You never change
  them: there is no proposal op for it.
- After an `event` line "The person changed the film's shape ...", run `moshfilm check <folder> --layout` and fix every
  scene that does not fit in each shape. Use `moshfilm check <folder> --layout --aspect 9:16` to try a shape before it
  is chosen.
- Captions (text clips) use `x` and `y` as fractions of the frame, and they apply to both shapes; the player wraps a
  caption near an edge. Place them where they fit both shapes. A caption that still cannot fit shows up in the layout
  check with the caption's id.

## 6b. Music and sound

Music and sound are optional. Add them after the scenes and the voice are ready, never before, and only when they help.
Everything is generated locally from parameters (nothing is downloaded); run `moshfilm sounds` to list the presets and
moods.

- Music: one bed per film, proposed once with `set_music` (`bed`: `mood`, `tempo` 60 to 160, `key`, `scale`,
  `palette`, `seed`; `volume` 0.4 to 0.6). Choose the mood from the film's tone: `calm` for explanations, `tense` for
  risks or attacks, `bright` or `playful` for light topics, `inspiring` for endings. The editor makes the bed exactly as
  long as the film and ducks it under the voice. Never replace music the person picked or supplied: such a proposal is
  held, and so is one that would bring back music they removed.
- Sound effects (`add_sfx`, with a full `sfx` object: a new `id` such as `fx1`, `scene`, `preset`, `at`, `volume`)
  mark a visual event: something appears, lands, is found, fails. Presets: `whoosh`, `swoosh-up`, `door`, `ding`,
  `pop`, `tick`, `click`, `success`, `error`, `typewriter`, `riser`, `thud`. Use them sparingly: at most 3 per scene, at
  least 0.4 s between two sounds, and many scenes have none.
- Placement: `at` is in seconds from the scene start (not a fraction of the length), and the clip follows its scene. A sound starts exactly at `at`; the part that runs past the end of
  its scene is faded out over the last 80 ms of the scene and cut (`moshfilm check` warns when more than 30% of a
  sound would be cut, so cue long sounds early enough). Time the matching beat in the scene code in seconds too (not as a fraction of `ctx.length`), so picture and sound stay
  together when the scene's length changes. Put a sound in the gap before or after the voice line, never on its key
  words, or keep it at volume 0.35 or less while the voice speaks. In gaps use volume 0.5 to 0.8.
- After placing sounds run `moshfilm check <folder>` and fix every sound warning it prints (over the narration, too
  close together, too many in a scene).
- An `event` line "The person removed the sound ..." or "... picked the music ..." means hands off: do not add the sound
  back and do not change that music unless they ask. A sound the person added or moved is pinned: `set_sfx` and
  `remove_sfx` on it are held for their approval.

## 7. Pacing

- One idea per scene.
- Voice lines of about 20 words or fewer.
- Give a scene at least its voice line plus a short pause; the editor does this for scenes whose length is not pinned.
  A pinned (manual) length wins and can be shorter than the voice, which then overflows: ask the person whether to
  stretch the scene or shorten the line.
- Pace in the panel (0.75 to 2.0, above 1 is slower) is the person's call; do not work around it.

## 8. Example

- `examples/example-scene.js`: a bar grows, then a label fades in; passes `moshfilm check` with no warnings.
- `examples/example-proposal.json`: a scene-list proposal with two scenes, waiting for approval.
- `examples/example-sound-proposal.json`: a calm music bed and two sound effects, applied without approval.

Command list:

- `moshfilm open <folder>`: start the editor (background).
- `moshfilm watch <folder>`: stream chat, comments and events (Monitor tool); `--once` for one batch.
- `moshfilm propose <folder> <file.json>`: send a proposal.
- `moshfilm reply <folder> <id> "<text>"`: answer an item and resolve it.
- `moshfilm say <folder> "<text>"`: chat message not tied to an item.
- `moshfilm status <folder> "<text>"` or `moshfilm status <folder> --clear`: progress line in the panel.
- `moshfilm plan <folder> --set "step" ...`, `--done N`, `--clear`: the plan checklist in the working card.
- `moshfilm hooks install <folder>` (`--uninstall` to remove): the Claude Code hooks behind the working card; needs a session restart.
- `moshfilm resolve <folder> <id>`: resolve without a reply.
- `moshfilm check <folder> [--layout] [--aspect A]`: validate the folder, scan scenes for non-deterministic code and warn about
  badly placed sounds;
  `--layout` also draws every ready scene in each shape and warns about content that sticks out or is clipped
  (`--aspect` adds a shape such as 9:16, repeatable).
- `moshfilm sounds`: list the sound-effect presets and music moods you can use (section 6b).
- `moshfilm voice <folder>`: make the narration and report how each line fits its scene.
- `moshfilm export <folder>`: render an MP4 (`--format gif` for a GIF, `-o <file>` for the output path). With a second
  shape it writes one file per shape (`<name>-16x9.mp4`, `<name>-9x16.mp4`). Export refuses scenes whose voice line
  does not fit; fix those instead of forcing it.
