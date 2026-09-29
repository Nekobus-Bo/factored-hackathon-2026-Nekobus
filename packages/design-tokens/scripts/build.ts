// Generate dist/ from src/tokens.json.
//
//   bun run scripts/build.ts            write dist/ (make design-tokens)
//   bun run scripts/build.ts --check    write nothing, fail if dist/ differs from what would be written
//
// dist/ is committed so apps and CI need no build step; --check is what keeps it honest.

import { mkdir, readdir, rm } from "node:fs/promises";
import { join, resolve } from "node:path";
import { generate, type Outputs } from "./generate";

export const PACKAGE_ROOT = resolve(import.meta.dir, "..");
export const TOKENS_PATH = join(PACKAGE_ROOT, "src/tokens.json");
export const DIST_DIR = join(PACKAGE_ROOT, "dist");

/** What dist/ must contain, generated from the committed src/tokens.json. */
export async function generateFromDisk(): Promise<Outputs> {
  const file = Bun.file(TOKENS_PATH);
  if (!(await file.exists())) throw new Error(`${TOKENS_PATH} is missing: copy tokens.json from the design-system artifact`);
  let json: unknown;
  try {
    json = JSON.parse(await file.text());
  } catch (error) {
    throw new Error(`src/tokens.json is not valid JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
  return generate(json);
}

async function listDist(): Promise<string[]> {
  try {
    return (await readdir(DIST_DIR)).sort();
  } catch {
    return [];
  }
}

function firstDifference(expected: string, actual: string): string {
  const want = expected.split("\n");
  const have = actual.split("\n");
  const length = Math.max(want.length, have.length);
  for (let index = 0; index < length; index++) {
    if (want[index] !== have[index]) {
      return `line ${index + 1}: expected ${JSON.stringify(want[index] ?? "<end of file>")}, found ${JSON.stringify(have[index] ?? "<end of file>")}`;
    }
  }
  return "contents differ";
}

/** Problems that make dist/ stale; empty when it matches. Reads only. */
export async function findDrift(outputs: Outputs): Promise<string[]> {
  const problems: string[] = [];
  for (const [name, expected] of Object.entries(outputs)) {
    const file = Bun.file(join(DIST_DIR, name));
    if (!(await file.exists())) {
      problems.push(`dist/${name} is missing`);
      continue;
    }
    const actual = await file.text();
    if (actual !== expected) problems.push(`dist/${name} is out of date (${firstDifference(expected, actual)})`);
  }
  for (const name of await listDist()) {
    if (!(name in outputs)) problems.push(`dist/${name} is not generated any more`);
  }
  return problems;
}

async function writeDist(outputs: Outputs): Promise<void> {
  await mkdir(DIST_DIR, { recursive: true });
  for (const [name, content] of Object.entries(outputs)) await Bun.write(join(DIST_DIR, name), content);
  for (const name of await listDist()) {
    if (!(name in outputs)) await rm(join(DIST_DIR, name), { recursive: true, force: true });
  }
}

async function main(): Promise<number> {
  const args = process.argv.slice(2);
  const unknown = args.filter((arg) => arg !== "--check");
  if (unknown.length > 0) {
    console.error(`design-tokens: unknown argument ${unknown.join(" ")} (only --check is accepted)`);
    return 2;
  }

  const outputs = await generateFromDisk();

  if (args.includes("--check")) {
    const problems = await findDrift(outputs);
    if (problems.length > 0) {
      console.error("design-tokens: dist/ does not match src/tokens.json");
      for (const problem of problems) console.error(`  - ${problem}`);
      console.error("Run `make design-tokens` and commit the result.");
      return 1;
    }
    console.log(`design-tokens: dist/ is up to date (${Object.keys(outputs).join(", ")})`);
    return 0;
  }

  await writeDist(outputs);
  console.log(`design-tokens: wrote ${Object.keys(outputs).map((name) => `dist/${name}`).join(", ")}`);
  return 0;
}

if (import.meta.main) {
  try {
    process.exitCode = await main();
  } catch (error) {
    console.error(`design-tokens: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}
