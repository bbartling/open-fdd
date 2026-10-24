/**
 * Count Playwright expect steps the JSON reporter drops.
 *
 * The stock JSON reporter keeps only category "test.step", so a required-run
 * gate cannot see expect() calls in that file. This reporter reads the live
 * result steps and writes passed-attempt counts for the gate.
 */
"use strict";

const fs = require("fs");

function countExpectSteps(steps) {
  if (!Array.isArray(steps)) {
    return 0;
  }
  let count = 0;
  for (const step of steps) {
    if (!step || typeof step !== "object") {
      continue;
    }
    if (step.category === "expect") {
      count += 1;
    }
    count += countExpectSteps(step.steps);
  }
  return count;
}

function redact(text) {
  let redacted = String(text || "");
  for (const key of [
    "OPENFDD_ADMIN_PASSWORD",
    "OPENFDD_CI_BROWSER_ADMIN_PASSWORD",
    "OPENFDD_CI_BROWSER_JWT_SECRET",
    "OPENFDD_JWT_SECRET",
  ]) {
    const secret = process.env[key];
    if (secret) {
      redacted = redacted.split(secret).join("[redacted]");
    }
  }
  return redacted;
}

function firstErrorLine(error) {
  if (!error || typeof error.message !== "string" || !error.message.trim()) {
    return "";
  }
  return redact(error.message).trim().split("\n")[0].slice(0, 240);
}

class ExpectCountReporter {
  constructor() {
    this.suite = null;
    this.attempts = new Map();
  }

  // The JSON reporter owns the report file. Claiming stdio here makes a
  // second --reporter flag replace that reporter, and the JSON never lands.
  printsToStdio() {
    return false;
  }

  onBegin(_config, suite) {
    this.suite = suite;
  }

  onTestEnd(test, result) {
    const list = this.attempts.get(test.id) || [];
    list.push({
      retry: result.retry,
      status: result.status,
      expect_steps: countExpectSteps(result.steps),
      error: firstErrorLine(result.error),
    });
    this.attempts.set(test.id, list);
  }

  async onEnd() {
    const file = process.env.OPENFDD_EXPECT_COUNT_FILE;
    if (!file) {
      throw new Error("OPENFDD_EXPECT_COUNT_FILE is required");
    }
    if (!this.suite || typeof this.suite.allTests !== "function") {
      throw new Error("Playwright suite was not provided");
    }
    const tests = [];
    for (const test of this.suite.allTests()) {
      const attempts = this.attempts.get(test.id) || [];
      let passedExpectSteps = 0;
      for (const attempt of attempts) {
        if (attempt.status === "passed") {
          passedExpectSteps += attempt.expect_steps;
        }
      }
      tests.push({
        id: test.id,
        title: test.titlePath().join(" :: "),
        outcome: test.outcome(),
        passed_expect_steps: passedExpectSteps,
        attempts,
      });
    }
    fs.writeFileSync(file, JSON.stringify({ tests }, null, 2), { mode: 0o600 });
  }
}

async function selfTest() {
  const failures = [];
  const nested = countExpectSteps([
    {
      category: "test.step",
      title: "Before Hooks",
      steps: [{ category: "expect", title: 'Expect "toBeVisible"', steps: [] }],
    },
    { category: "pw:api", title: "GET", steps: [] },
  ]);
  if (nested !== 1) {
    failures.push(`nested expect count was ${nested}`);
  }
  const titled = countExpectSteps([
    { category: "test.step", title: "Expect toBeVisible", steps: [] },
  ]);
  if (titled !== 0) {
    failures.push("test.step titled Expect was counted");
  }
  if (countExpectSteps([]) !== 0 || countExpectSteps(undefined) !== 0) {
    failures.push("empty step list was not zero");
  }
  const previous = process.env.OPENFDD_ADMIN_PASSWORD;
  process.env.OPENFDD_ADMIN_PASSWORD = "secret-value";
  const hidden = firstErrorLine({ message: "filled secret-value into the form" });
  if (previous === undefined) {
    delete process.env.OPENFDD_ADMIN_PASSWORD;
  } else {
    process.env.OPENFDD_ADMIN_PASSWORD = previous;
  }
  if (hidden.includes("secret-value") || !hidden.includes("[redacted]")) {
    failures.push("error text was not redacted");
  }

  if (new ExpectCountReporter().printsToStdio() !== false) {
    failures.push("expect reporter claimed stdio and would hide the JSON report");
  }

  const file = require("path").join(require("os").tmpdir(), `openfdd-expect-count-${process.pid}.json`);
  process.env.OPENFDD_EXPECT_COUNT_FILE = file;
  const reporter = new ExpectCountReporter();
  const test = {
    id: "t-pass",
    titlePath() {
      return ["chromium", "e2e/smoke.spec.ts", "shell"];
    },
    outcome() {
      return "flaky";
    },
  };
  reporter.onBegin(null, {
    allTests() {
      return [test];
    },
  });
  reporter.onTestEnd(test, {
    retry: 0,
    status: "timedOut",
    steps: [{ category: "expect", title: 'Expect "toBeVisible"', steps: [] }],
    error: { message: "Timeout 15000ms exceeded" },
  });
  reporter.onTestEnd(test, {
    retry: 1,
    status: "passed",
    steps: [
      {
        category: "test.step",
        title: "Before Hooks",
        steps: [
          { category: "expect", title: 'Expect "toBeVisible"', steps: [] },
          { category: "expect", title: 'Expect "toEqual"', steps: [] },
          { category: "pw:api", title: "GET /", steps: [] },
        ],
      },
    ],
    error: undefined,
  });
  await reporter.onEnd();
  const body = JSON.parse(fs.readFileSync(file, "utf8"));
  fs.unlinkSync(file);
  const row = body.tests && body.tests[0];
  if (!row || row.passed_expect_steps !== 2 || row.outcome !== "flaky" || row.id !== "t-pass") {
    failures.push(`passing retry did not record two expect steps (${JSON.stringify(body)})`);
  }
  delete process.env.OPENFDD_EXPECT_COUNT_FILE;
  const bare = new ExpectCountReporter();
  bare.onBegin(null, { allTests() { return []; } });
  try {
    await bare.onEnd();
    failures.push("missing expect-count path was accepted");
  } catch (err) {
    if (!String(err && err.message).includes("OPENFDD_EXPECT_COUNT_FILE")) {
      failures.push(`missing path raised the wrong error (${err})`);
    }
  }

  if (failures.length) {
    console.error("playwright_expect_reporter --self-test FAILED:");
    for (const item of failures) {
      console.error(`  - ${item}`);
    }
    return 1;
  }
  console.log("playwright_expect_reporter --self-test OK (positive=2 negative=5)");
  return 0;
}

module.exports = ExpectCountReporter;
module.exports.countExpectSteps = countExpectSteps;

if (require.main === module && process.argv.includes("--self-test")) {
  selfTest()
    .then((code) => process.exit(code))
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
