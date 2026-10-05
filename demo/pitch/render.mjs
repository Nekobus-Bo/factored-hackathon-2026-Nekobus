// Frame-accurate render of film.html: seeks the master timeline frame by frame, screenshots the
// 1920x1080 stage and pipes the frames to ffmpeg. Also writes film.local.html (the page wrapped in a
// full document) so the film can be opened locally.
//
//   node render.mjs                         # film-1080p.mp4 at 30 fps, no captions
//   node render.mjs --fps 60 --captions     # 60 fps with the draft captions burned in
//   node render.mjs --from 104 --to 124     # one stretch only (seconds)
//   node render.mjs --shots 5,45,120        # PNG stills to shots/ (review)
//   node render.mjs --wrap-only             # just write film.local.html
//
// Needs: ffmpeg on PATH, Google Chrome installed, and playwright-core (npm i --no-save playwright-core).
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const flag = (name) => args.includes(`--${name}`);
const opt = (name, fallback) => { const i = args.indexOf(`--${name}`); return i >= 0 ? args[i + 1] : fallback; };

const body = readFileSync(join(here, "film.html"), "utf8");
const local = `<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n</head>\n<body>\n${body}\n</body>\n</html>\n`;
writeFileSync(join(here, "film.local.html"), local);
if (flag("wrap-only")) { console.log("wrote film.local.html"); process.exit(0); }

const { chromium } = await import("playwright-core");
const fps = Number(opt("fps", 30));
const from = Number(opt("from", 0));
const to = Number(opt("to", 180));
const captions = flag("captions");
const url = pathToFileURL(join(here, "film.local.html")).href + `?capture=1${captions ? "&captions=1" : ""}`;

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
page.on("pageerror", (e) => console.error("page error:", e.message));
await page.goto(url, { waitUntil: "networkidle" });
await page.evaluate(() => window.film.ready);
await page.waitForTimeout(300);
const stage = await page.$("#stage");

if (opt("shots")) {
  const dir = join(here, "shots");
  mkdirSync(dir, { recursive: true });
  for (const t of opt("shots").split(",").map(Number)) {
    await page.evaluate((s) => window.film.seek(s), t);
    const file = join(dir, `t${String(t.toFixed(2)).padStart(6, "0")}.png`);
    await stage.screenshot({ path: file });
    console.log(file);
  }
  await browser.close();
  process.exit(0);
}

const out = join(here, opt("out", from === 0 && to === 180 ? `film-1080p${fps}.mp4` : `film-${from}-${to}.mp4`));
const ff = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(fps), "-i", "-",
  "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-r", String(fps), "-movflags", "+faststart", out],
  { stdio: ["pipe", "inherit", "inherit"] });
const total = Math.round((to - from) * fps);
const started = Date.now();
for (let i = 0; i < total; i++) {
  const t = from + i / fps;
  await page.evaluate((s) => window.film.seek(s), t);
  const png = await stage.screenshot({ type: "png" });
  if (!ff.stdin.write(png)) await new Promise((r) => ff.stdin.once("drain", r));
  if (i % fps === 0) process.stdout.write(`\r${(t).toFixed(0)}s / ${to}s  (${((Date.now() - started) / 1000).toFixed(0)}s elapsed)`);
}
ff.stdin.end();
await new Promise((r) => ff.on("close", r));
await browser.close();
console.log(`\nwrote ${out}`);
