# Pitch film

The 3:00 pitch video, built as an HTML animation from the product's design system and rendered frame by frame. Presentation material, not product code. It stays outside `make` on purpose: it needs Node, Google Chrome and ffmpeg, which the product does not.

| File | What it is |
|---|---|
| `film.html`, `film.js`, `film.css` | The film: a 1920×1080 stage, one GSAP timeline of exactly 180 s, 13 scenes |
| `tokens.css`, `components.css`, `local.css`, `app.css` | Copies of the stylesheets the customer page loads: `packages/design-tokens/{dist/tokens.css, src/components.css, local.css}` and `apps/web-client/src/app/app.css` |
| `capture-ui.tsx`, `capture-ui.sh` | Renders the product's real customer page to `ui-chat.html`, which S04 shows |
| `mix.sh` | The final mix: picture, music, narration |
| `script.md` | Narration script with timings, emphasis, sources, music and sound cues |
| `captions.srt` | The voice-over draft as subtitles, at the animatic's timings |
| `render.mjs` | Frame-accurate renderer (Chrome via playwright-core, then ffmpeg) |

Animatic, this cut, playable and scrubbable (shared: anyone with the link): https://claude.ai/artifact/7HWUGZ4ttfUE7YwwzjyggW

## S04 shows the real product

S04 does not mock the chat up: `capture-ui.tsx` renders the app's own React components — the same
`Landing`, `ChatDock`, `Transcript` and `Blocks` that ship, with the same stylesheets — to static HTML,
the way `apps/web-client/tests/render.test.tsx` already does. `render.mjs` inlines the result into the
lid of the computer in S04, and `film.js` plays the conversation back on the timeline.

```bash
./capture-ui.sh                  # writes ui-chat.html; needs bun and apps/web-client/node_modules
```

Run it again whenever the chat UI changes, then re-render. It fails with an explicit message if the
markup it anchors to has moved. Without `ui-chat.html` the render still runs and says the lid is empty.

## Preview locally

```bash
node render.mjs --wrap-only      # writes film.local.html, with the real page inlined into S04
open film.local.html             # #S07 jumps to a scene; ?capture=1 shows the bare stage
```

`film.html` opened on its own shows S04 with an empty screen: the real page is only inlined by
`render.mjs`, so the generated markup stays out of the film's diffs.

## Render

Needs ffmpeg, Google Chrome and `npm i --no-save --no-package-lock --no-workspaces playwright-core` in this folder (a `package.json` keeps the install here).

```bash
node render.mjs                          # film-1080p30.mp4, silent, no captions (~6 min)
node render.mjs --fps 60                 # smoother, twice as long
node render.mjs --captions               # draft captions burned in by the page
node render.mjs --from 104 --to 124      # one stretch
node render.mjs --shots 52,109,176       # PNG stills in shots/
```

## The mix

The music (`aud_eva1.wav`) was cut to the picture, and its seams land on the scene boundaries: a section
change at 27.9 s (the alarm, boundary 28), another at 89.3 s (the teardown, boundary 90), the drop at
120.7 s (the thesis) and a hard seam at 153.5 s (next episode, boundary 154). **So the picture is fixed
and everything else is fitted to it.** When a scene needs more reading time, the time comes from inside
that scene, never from a boundary.

The narration (`voice1.mp4`) runs about 5 % longer than the timings in `script.md`. `mix.sh` takes the
whole take to exactly 180 s with one `atempo`: nothing is cut, the pitch does not move, and 5 % is under
what a listener hears as fast. It leaves each line within a second or two of its cue — close enough for
the film, and if you want them exactly on the beat, cut the take into its lines by ear and lay them on
the times in `script.md`.

```bash
./mix.sh --check                 # the numbers it will use, without rendering
./mix.sh                         # pattern-blue-pitch.mp4
./mix.sh --captions              # also pattern-blue-pitch-cc.mp4, captions burned in
```

It prints its own check at the end: 3:00 at 1920×1080, about −14 LUFS.

## Rules this film keeps

- Every number on screen traces to a versioned report or a cited source (`script.md`, "Where every number comes from").
- IP-safe homage: no franchise name, logos, characters, footage or the show's music. Royalty-free music only.
- Everything on stage moves on the timeline (CSS animations are switched off inside it), so any frame reproduces exactly.
