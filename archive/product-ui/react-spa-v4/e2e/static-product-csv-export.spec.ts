import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { failIfRequired, stackRequired } from "./requireStack";
import { ensureProductSession } from "./session";

const centralBase =
  process.env.OPENFDD_STATIC_UI_BASE_URL ?? "http://127.0.0.1:8080";

const seededBuildingId = (process.env.OPENFDD_STATIC_UI_BROWSER_BUILDING_ID ?? "").trim();

function pathWithSite(site: string): string {
  const url = new URL("/app/?tab=ops", centralBase);
  if (site) url.searchParams.set("site", site);
  return `${url.pathname}${url.search}`;
}

async function waitForAppBoot(page: import("@playwright/test").Page): Promise<void> {
  await expect(page.locator("#logoutBtn")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator("#tabs")).toBeVisible({ timeout: 15_000 });
}

async function ensureSiteSelected(
  page: import("@playwright/test").Page,
  siteId: string,
): Promise<void> {
  await page.evaluate((site) => {
    const pick = document.getElementById("sitePick") as HTMLSelectElement | null;
    if (!pick) return;
    let opt = pick.querySelector(`option[value="${site}"]`) as HTMLOptionElement | null;
    if (!opt) {
      opt = document.createElement("option");
      opt.value = site;
      opt.textContent = site;
      pick.appendChild(opt);
    }
    pick.value = site;
    pick.dispatchEvent(new Event("change", { bubbles: true }));
  }, siteId);
  await expect(page.locator("#liveTxt")).not.toHaveText("loading…", { timeout: 60_000 });
  await expect(page.locator("#sub")).toContainText(siteId, { timeout: 60_000 });
}

function validateZipCsv(zipPath: string): void {
  const script = `
import json, sys, zipfile
from datetime import datetime

zip_path = sys.argv[1]
with zipfile.ZipFile(zip_path) as zf:
    names = zf.namelist()
    if names != ["site_history.csv"]:
        raise SystemExit(f"unexpected zip entries: {names}")
    raw = zf.read("site_history.csv")

if raw.startswith(b"\\xef\\xbb\\xbf"):
    raw = raw[3:]

try:
    text = raw.decode("utf-8")
except UnicodeDecodeError as exc:
    raise SystemExit(f"not valid UTF-8: {exc}") from exc

lines = text.splitlines()
if not lines:
    raise SystemExit("empty CSV")
header = lines[0].split(",")
if header[0] != "timestamp_utc":
    raise SystemExit(f"bad header first column: {header[0]!r}")
required = ["timestamp_utc", "equipment_id", "point", "role", "unit", "value"]
for col in required:
    if col not in header:
        raise SystemExit(f"missing column {col} in {header}")

prev = None
for i, line in enumerate(lines[1:], start=2):
    if not line.strip():
        continue
    ts = line.split(",", 1)[0]
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"line {i}: bad timestamp {ts!r}: {exc}") from exc
    if prev is not None and dt < prev:
        raise SystemExit(f"line {i}: out-of-order timestamp {ts}")
    prev = dt

print(json.dumps({"rows": max(0, len(lines) - 1), "encoding": "utf-8"}))
`;
  const out = execFileSync("python3", ["-c", script, zipPath], {
    encoding: "utf8",
    maxBuffer: 10 * 1024 * 1024,
  });
  const parsed = JSON.parse(out.trim()) as { rows: number; encoding: string };
  if (parsed.encoding !== "utf-8") {
    throw new Error(`unexpected encoding marker: ${parsed.encoding}`);
  }
}

test.describe("static product CSV export", () => {
  test.beforeEach(async ({ page, request }) => {
    if (!stackRequired) {
      test.skip(true, "OPENFDD_PLAYWRIGHT_REQUIRE_STACK not set");
    }
    await ensureProductSession(page, request);
  });

  test("ops export downloads site_history zip with ordered UTF-8 CSV", async ({ page }) => {
    const site = seededBuildingId;
    if (!site) {
      failIfRequired("OPENFDD_STATIC_UI_BROWSER_BUILDING_ID required for CSV export gate");
      return;
    }

    await page.goto(pathWithSite(site));
    await waitForAppBoot(page);
    await ensureSiteSelected(page, site);

    await expect(page.locator("#csvExportBtn")).toBeEnabled({ timeout: 30_000 });

    const downloadPromise = page.waitForEvent("download", { timeout: 120_000 });
    await page.locator("#csvExportBtn").click();
    const download = await downloadPromise;

    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "openfdd-csv-export-"));
    const zipPath = path.join(tmpDir, download.suggestedFilename() || "site_history.zip");
    await download.saveAs(zipPath);

    try {
      expect(fs.statSync(zipPath).size).toBeGreaterThan(0);
      validateZipCsv(zipPath);
    } finally {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    }
  });
});
