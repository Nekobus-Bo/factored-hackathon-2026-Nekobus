# Pitch film

The 3:00 pitch video, built as an HTML animation from the product's design system and rendered frame by frame. Presentation material, not product code. It stays outside `make` on purpose: it needs Node, Google Chrome and ffmpeg, which the product does not.

| File | What it is |
|---|---|
| `film.html`, `film.js`, `film.css` | The film: a 1920×1080 stage, one GSAP timeline of exactly 180 s, 13 scenes |
| `tokens.css`, `components.css` | Copies of `packages/design-tokens/dist/tokens.css` and `src/components.css` |
| `script.md` | Narration script with timings, emphasis, sources, music and sound cues |
| `captions.srt` | The voice-over draft as subtitles, at the animatic's timings |
| `render.mjs` | Frame-accurate renderer (Chrome via playwright-core, then ffmpeg) |

Animatic (private, shareable from its Share menu): https://claude.ai/artifact/7HWUGZ4ttfUE7YwwzjyggW

## Preview locally

```bash
node render.mjs --wrap-only      # writes film.local.html
open film.local.html             # #S07 jumps to a scene; ?capture=1 shows the bare stage
```

## Render

Needs ffmpeg, Google Chrome and `npm i --no-save --no-package-lock --no-workspaces playwright-core` in this folder (a `package.json` keeps the install here).

```bash
node render.mjs                          # film-1080p30.mp4, silent, no captions (~6 min)
node render.mjs --fps 60                 # smoother, twice as long
node render.mjs --captions               # draft captions burned in by the page
node render.mjs --from 104 --to 124      # one stretch
node render.mjs --shots 52,109,176       # PNG stills in shots/
```

## After the voice-over is recorded

Drop the take in this folder as `vo.wav`. To find where each phrase starts (for retiming the scenes to the voice):

```bash
ffmpeg -i vo.wav -af silencedetect=noise=-35dB:d=0.35 -f null - 2>&1 | grep silence_end
```

Then move the scene times in `film.js` (`SCENES`, `CAPTIONS` and the timeline positions) and render again.

## Mix without an editor

Voice-over on top, music ducked under it, captions burned in:

```bash
ffmpeg -i film-1080p30.mp4 -i vo.wav -i music.mp3 -filter_complex \
 "[2:a]volume=0.35[m];[m][1:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck];\
  [duck][1:a]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a];\
  [0:v]subtitles=captions.srt:force_style='FontName=IBM Plex Sans,FontSize=20,BorderStyle=3,Outline=6,BackColour=&H99000000'[v]" \
 -map "[v]" -map "[a]" -c:v libx264 -crf 16 -pix_fmt yuv420p -c:a aac -b:a 192k -shortest pattern-blue-pitch.mp4
```

Check before uploading: `ffprobe pattern-blue-pitch.mp4` shows 3:00 at 1920×1080, and `ffmpeg -i pattern-blue-pitch.mp4 -af ebur128 -f null -` reads about −14 LUFS.

## Rules this film keeps

- Every number on screen traces to a versioned report or a cited source (`script.md`, "Where every number comes from").
- IP-safe homage: no franchise name, logos, characters, footage or the show's music. Royalty-free music only.
- Everything on stage moves on the timeline (CSS animations are switched off inside it), so any frame reproduces exactly.
