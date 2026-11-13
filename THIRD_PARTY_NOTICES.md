# Third-party notices

moshFilm itself is MIT licensed (see `LICENSE`). This file covers code that is **bundled inside this repository**.
Libraries that are only installed as dependencies (for example `edge-tts`, `playwright`, `numpy`, `fastapi`) are not
copied here; pip fetches them with their own licences.

## Bundled in `src/moshfilm/static/assets/` (the built editor)

The files `index-*.js`, `player-*.js` and `render-*.js` are the minified output of the UI in `ui/`. They contain the
following code, which is why this notice exists (minification removes the licence banners).

### Vue 3.5.45 (`vue`, with `@vue/runtime-core`, `@vue/runtime-dom`, `@vue/reactivity` and `@vue/shared`)

MIT License. Source: https://github.com/vuejs/core

```
The MIT License (MIT)

Copyright (c) 2018-present, Yuxi (Evan) You and Vue contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Vite module-preload helper

`player-*.js` starts with a small module-preload helper that the Vite build tool (MIT, https://github.com/vitejs/vite)
adds to every build. It is covered by the same MIT terms: Copyright (c) 2019-present, VoidZero Inc. and Vite contributors.

## Not bundled

- **Fonts**: none. The editor uses the system font stacks.
- **Images and audio**: none besides the editor screenshot in `docs/`. Music and sound effects are synthesised at
  runtime, so no audio files or soundfonts ship with the code.
- **Sample film** (`src/moshfilm/samples/`): original script and drawings.

## Runtime dependencies worth knowing about

- `edge-tts` (LGPL-3.0) is installed by pip and imported unchanged; it is not vendored. See "Narration and privacy"
  in the README.
- Playwright downloads Chromium separately into its own cache folder; Chromium is not part of this repository.
