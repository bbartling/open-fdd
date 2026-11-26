#!/usr/bin/env node
// Runs the contract suite (run.mjs) against the mock in three host profiles:
// auth on + writes off (the default), auth on + writes on, auth off + writes on.
//   node contract/test/selftest.mjs        (or: cd contract && npm test)
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SERVER = path.join(HERE, "..", "mock", "server.mjs");
const SUITE = path.join(HERE, "run.mjs");

const PROFILES = [
  { name: "auth on, writes off", args: [] },
  { name: "auth on, writes on", args: ["--writes"] },
  { name: "auth off, writes on", args: ["--no-auth", "--writes"] },
];

function startMock(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [SERVER, "--port", "0", ...args], { stdio: ["ignore", "pipe", "inherit"] });
    let out = "";
    child.stdout.on("data", (d) => {
      out += d;
      const m = /on (http:\/\/[^\s]+)/.exec(out);
      if (m) resolve({ child, base: m[1] });
    });
    child.on("exit", (code) => reject(new Error(`mock exited (${code}) before listening`)));
  });
}

function runSuite(base) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [SUITE, "--base", base], { stdio: "inherit" });
    child.on("exit", (code) => resolve(code ?? 1));
  });
}

let failed = 0;
for (const p of PROFILES) {
  console.log(`\n=== contract suite against the mock: ${p.name} ===`);
  const { child, base } = await startMock(p.args);
  const code = await runSuite(base);
  child.removeAllListeners("exit");
  child.kill();
  if (code !== 0) failed++;
}
console.log(failed ? `\n${failed} profile(s) failed` : "\nall profiles passed");
process.exit(failed ? 1 : 0);
