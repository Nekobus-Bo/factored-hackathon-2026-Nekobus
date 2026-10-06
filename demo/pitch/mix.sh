#!/usr/bin/env bash
# The final mix: the rendered picture, the edited music under the narration, captions optional.
#
#   ./mix.sh                 # pattern-blue-pitch.mp4
#   ./mix.sh --captions      # also pattern-blue-pitch-cc.mp4, captions burned in
#   ./mix.sh --check         # print the numbers it would use and stop
#
# The picture is fixed at 180 s because the music was cut to it (its seams land on the scene
# boundaries: 27.9 s, 89.3 s, 120.7 s, 153.5 s). So the voice is fitted to the picture, not the other
# way round: the take runs about 5 % long, and one `atempo` over the whole take takes it to exactly
# 180 s. Nothing is cut, the pitch does not move, and 5 % is under what a listener hears as fast. It
# leaves each line within a second or two of its cue; to place them exactly, cut the take into its
# lines by ear and lay them on the times in `script.md`.
set -euo pipefail
cd "$(dirname "$0")"

VIDEO=${VIDEO:-film-1080p30.mp4}
VOICE=${VOICE:-voice1.mp4}
MUSIC=${MUSIC:-aud_eva1.wav}
OUT=${OUT:-pattern-blue-pitch.mp4}
FILM=180            # the length of the picture, and of the mix
VOICE_TARGET=-16    # LUFS: the narration in front
MUSIC_TARGET=-27    # LUFS: the bed under it, before ducking
FIRST_WORD=3.0      # where the first line starts in the film (script.md, S01)

captions=0; check=0
for arg in "$@"; do
  case "$arg" in
    --captions) captions=1 ;;
    --check) check=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

for f in "$VIDEO" "$VOICE" "$MUSIC"; do
  [ -f "$f" ] || { echo "missing $f. Render the picture with 'node render.mjs' and keep the music and the take in this folder." >&2; exit 1; }
done

seconds() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }
lufs() { ffmpeg -hide_banner -nostats -i "$1" -map 0:a -af ebur128 -f null - 2>&1 | grep -A2 "Integrated loudness" | awk '/I: /{print $2}' | tail -1; }

take=$(seconds "$VOICE")
tempo=$(awk -v t="$take" -v f="$FILM" 'BEGIN{printf "%.6f", t/f}')
voice_lufs=$(lufs "$VOICE"); music_lufs=$(lufs "$MUSIC")
voice_gain=$(awk -v a="$VOICE_TARGET" -v b="$voice_lufs" 'BEGIN{printf "%.2f", a-b}')
music_gain=$(awk -v a="$MUSIC_TARGET" -v b="$music_lufs" 'BEGIN{printf "%.2f", a-b}')
# The take's first word, so it lands on the film's first cue rather than wherever the recording started.
onset=$(ffmpeg -v info -i "$VOICE" -map 0:a -af "silencedetect=noise=-33dB:d=0.5" -f null - 2>&1 \
        | grep -oE "silence_end: [0-9.]+" | head -1 | grep -oE "[0-9.]+")
onset=${onset:-0}
delay=$(awk -v o="$onset" -v r="$tempo" -v w="$FIRST_WORD" 'BEGIN{d=w-o/r; printf "%.0f", (d>0?d:0)*1000}')

printf 'picture   %s s\n' "$(seconds "$VIDEO")"
printf 'take      %s s -> atempo %s -> %s s\n' "$take" "$tempo" "$FILM"
printf 'first word %.2f s in the take -> %.2f s in the mix (+%s ms)\n' "$onset" "$FIRST_WORD" "$delay"
printf 'voice     %s LUFS %+.2f dB\n' "$voice_lufs" "$voice_gain"
printf 'music     %s LUFS %+.2f dB, ducked under the voice\n' "$music_lufs" "$music_gain"
[ "$check" = 1 ] && exit 0

# [1] the take: to the film's length, up to level, placed on the first cue, padded to 180 s.
# [2] the music: down to the bed level, then ducked by the voice (sidechaincompress keys off it).
filter="[1:a]atempo=${tempo},volume=${voice_gain}dB,adelay=${delay}|${delay},apad,atrim=0:${FILM},asetpts=N/SR/TB[vo];\
[vo]asplit=2[vo1][key];\
[2:a]volume=${music_gain}dB,apad,atrim=0:${FILM},asetpts=N/SR/TB[mu];\
[mu][key]sidechaincompress=threshold=0.02:ratio=6:attack=25:release=350[duck];\
[duck][vo1]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,apad,atrim=0:${FILM},asetpts=N/SR/TB[a]"

ffmpeg -y -loglevel error -i "$VIDEO" -i "$VOICE" -i "$MUSIC" -filter_complex "$filter" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -t "$FILM" "$OUT"
echo "wrote $OUT"

# A subtitle track the viewer can switch on, rather than burned in: this ffmpeg has no libass, and a
# track is kinder anyway. To burn them in instead, use an ffmpeg built with libass and its `subtitles`
# filter with captions.srt.
if [ "$captions" = 1 ]; then
  cc=${OUT%.mp4}-cc.mp4
  ffmpeg -y -loglevel error -i "$OUT" -i captions.srt \
    -map 0:v -map 0:a -map 1 -c:v copy -c:a copy -c:s mov_text -metadata:s:s:0 language=eng "$cc"
  echo "wrote $cc (captions as a track you can switch on)"
fi

echo
echo "check:"
ffprobe -v error -show_entries format=duration -show_entries stream=width,height -of default=noprint_wrappers=1 "$OUT"
ffmpeg -hide_banner -nostats -i "$OUT" -af ebur128 -f null - 2>&1 | grep -A2 "Integrated loudness" | awk '/I: /{print "  integrated " $2 " LUFS (want about -14)"}' | tail -1
