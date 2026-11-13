# Known issues

Small things that are known and do not block use of moshFilm 1.0.

- **Export is slow.** Every frame is one Chromium screenshot, so a long film at 30 fps takes minutes.
- **Narration needs the network** (see "Narration and privacy" in the README). Use `--no-voice` to export without it.
- **"Show in folder"** in the editor works on macOS only. Elsewhere, open the `exports/` folder yourself.
- **Undo** covers `film.json` and the top-level `scenes/*.js` files only.
- **Odd widths.** `--width` with an odd number can make an MP4 that some players reject (the H.264 `yuv420p` format needs even sizes). Use an even width.
- **No upload size limit** on files you add through the editor; it only listens on `127.0.0.1`, so this affects only you.
- **Hand-written scene code.** `moshfilm check` looks for `Date.now`, `new Date` and `Math.random` only; other sources of non-determinism are not detected.
- **Timeline drags.** A very small drag on a caption or voice clip can still pin it.
