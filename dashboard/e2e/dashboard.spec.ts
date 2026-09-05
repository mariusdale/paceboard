/**
 * End-to-end flow against fixture mode.
 *
 * The suite runs on a scratch database seeded with clearly labelled synthetic
 * data and a deliberately unreachable Garmin MCP, so it exercises both the
 * populated views and the disconnected-provider states without touching a real
 * account.
 */
import { expect, test, type Page } from "@playwright/test";

test.describe("Paceboard dashboard", () => {
  test.beforeEach(async ({ page }) => {
    page.on("pageerror", (error) => {
      throw new Error(`Uncaught page error: ${error.message}`);
    });
  });

  /** Navigate via the rail, so in-page links of the same name never match. */
  const goto = (page: Page, name: string) =>
    page.getByRole("navigation", { name: "Sections" }).getByRole("link", { name, exact: true }).click();

  test("the full navigation flow renders real stored data on every page", async ({ page }) => {
    await page.goto("/");

    // Fixture mode must announce itself; synthetic data may never masquerade
    // as measured data.
    await expect(page.getByTestId("fixture-banner")).toContainText("Fixture mode");

    // --- Overview
    await expect(page.getByRole("heading", { name: "Your night, at a glance" })).toBeVisible();
    await expect(page.locator(".score-center > span")).toHaveText(/\d/);
    await expect(page.locator(".vital")).toHaveCount(4);
    await expect(page.getByRole("heading", { name: "Your rhythm over time" })).toBeVisible();
    await page.getByRole("button", { name: "HRV", exact: true }).click();
    await expect(page.getByRole("button", { name: "HRV", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "7D", exact: true }).click();
    await expect(page.getByRole("button", { name: "7D", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".activity-item").first()).toBeVisible();

    // --- Activities
    await goto(page, "Activities");
    await expect(page.getByRole("heading", { name: "Activities", level: 1 })).toBeVisible();

    const rows = page.locator("table tbody tr");
    await expect(rows.first()).toBeVisible();
    const totalRows = await rows.count();
    expect(totalRows).toBeGreaterThan(5);

    // Filtering narrows the set and is reflected in the table.
    await page.getByLabel("Sport").selectOption("run");
    await expect(page.locator("table tbody tr td:nth-child(2)").first()).toHaveText("Run");
    const runRows = await page.locator("table tbody tr").count();
    expect(runRows).toBeLessThanOrEqual(totalRows);

    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page.locator("table tbody tr")).toHaveCount(totalRows);

    // --- Activity detail
    await page.locator("table tbody tr td a").first().click();
    await expect(page.locator("h1")).toContainText(/Fixture/);
    await expect(page.getByRole("heading", { name: "Session charts" })).toBeVisible();
    await expect(page.locator(".recharts-surface").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Laps" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Time in heart-rate zones" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Derived analysis" })).toBeVisible();

    // A metric with no source data says so rather than showing a number.
    await expect(page.locator(".readout-value.na")).toHaveCount(0);
    await expect(page.getByText("About data coverage", { exact: true })).toBeVisible();

    // --- Recovery
    await goto(page, "Recovery");
    await expect(page.getByRole("heading", { name: "Recovery", level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Sleep stages" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "HRV and baseline" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recovery against load" })).toBeVisible();
    expect(await page.locator(".recharts-surface").count()).toBeGreaterThan(3);

    await page.getByRole("button", { name: "30 days" }).click();
    await expect(page.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");

    // --- Training
    await goto(page, "Training");
    await expect(page.getByRole("heading", { name: "Performance management chart" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Intensity distribution" })).toBeVisible();
    await expect(page.locator(".zonebar")).toBeVisible();

    // --- Data Explorer
    await goto(page, "Data Explorer");
    await expect(page.getByRole("heading", { name: "Capability catalog" })).toBeVisible();
    await expect(page.locator("table tbody tr").first()).toBeVisible();

    await page.getByRole("tab", { name: "Raw payloads" }).click();
    await expect(page.getByRole("heading", { name: "Raw payloads" })).toBeVisible();
    await page.locator("table tbody tr").first().click();
    await expect(page.locator("pre.json")).toBeVisible();

    // --- Connections
    await goto(page, "Connections");
    await expect(page.getByRole("heading", { name: "Garmin MCP" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Strava" })).toBeVisible();
    await expect(page.getByText("Strava not connected.")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Storage" })).toBeVisible();
  });

  test("units switch between metric and imperial everywhere", async ({ page }) => {
    await page.goto("/settings");
    await page.getByRole("button", { name: "Imperial" }).click();
    await expect(page.getByRole("button", { name: "Imperial" })).toHaveAttribute("aria-pressed", "true");

    await goto(page, "Activities");
    await expect(page.locator("table tbody tr").first()).toBeVisible();
    await expect(page.locator("table tbody").first()).toContainText("mi");

    await goto(page, "Connections");
    await page.getByRole("button", { name: "Metric" }).click();
    await goto(page, "Activities");
    await expect(page.locator("table tbody").first()).toContainText("km");
  });

  test("a disconnected Garmin MCP is reported, not hidden", async ({ page }) => {
    await page.goto("/settings");
    // The e2e server points GARMIN_MCP_URL at a closed port on purpose.
    await expect(page.getByText(/cannot reach the Garmin MCP server/i)).toBeVisible();
    await expect(page.getByText("garmin-mcp-readonly.sh")).toBeVisible();
  });

  test("the manual tool form refuses anything outside the read-only allowlist", async ({ page }) => {
    await page.goto("/explorer");
    await page.getByRole("tab", { name: "Run a read tool" }).click();

    const options = await page.locator("select >> nth=0").locator("option").allTextContents();
    const mutating = options.filter((option) =>
      /^(set_|add_|create_|delete_|update_|upload_|log_|schedule_|download_)/.test(option.trim()),
    );
    expect(mutating, `mutating tools offered: ${mutating.join(", ")}`).toHaveLength(0);
    expect(options.length).toBeGreaterThan(20);
  });

  test("empty and unavailable states explain themselves", async ({ page }) => {
    await page.goto("/activities");
    await page.getByLabel("Search name").fill("no-such-activity-anywhere");
    await expect(page.getByText("No activities match these filters")).toBeVisible();
    await expect(page.getByText(/widening the date range/i)).toBeVisible();
  });

  test("backfill supports a year and custom days with validation", async ({ page }) => {
    const requests: Record<string, unknown>[] = [];
    await page.route("**/api/v1/sync", async route => {
      if (route.request().method() === "POST") {
        requests.push(route.request().postDataJSON());
        await route.fulfill({ json: { accepted: true } });
      } else await route.continue();
    });
    await page.goto("/settings");
    await page.getByLabel("Backfill history", { exact: true }).selectOption("365");
    await page.getByRole("button", { name: "Backfill 365 days", exact: true }).click();
    await expect.poll(() => requests.length).toBe(1);
    expect(requests[0]).toMatchObject({ mode: "backfill" });
    const windowDays = (request: Record<string, unknown>) => (Date.parse(String(request.end)) - Date.parse(String(request.start))) / 86400000 + 1;
    expect(windowDays(requests[0])).toBe(365);
    await page.getByLabel("Backfill history", { exact: true }).selectOption("custom");
    await page.getByLabel("Custom backfill days").fill("730");
    await page.getByRole("button", { name: "Backfill 730 days", exact: true }).click();
    await expect.poll(() => requests.length).toBe(2);
    expect(windowDays(requests[1])).toBe(730);
    await page.getByLabel("Custom backfill days").fill("0");
    await expect(page.getByRole("button", { name: "Backfill custom days" })).toBeDisabled();
    await page.getByLabel("Custom backfill days").fill("3651");
    await expect(page.getByRole("button", { name: "Backfill custom days" })).toBeDisabled();
  });

  test("recovery can navigate a full year and an empty historical period", async ({ page }) => {
    await page.goto("/recovery");
    await page.getByRole("button", { name: "1 year", exact: true }).click();
    await expect(page.getByRole("button", { name: "1 year", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "Previous period" }).click();
    await expect(page.getByLabel("Recovery from")).toBeVisible();
    await page.getByLabel("Recovery from").fill("2020-01-01");
    await page.getByLabel("Recovery to").fill("2020-01-31");
    await expect(page.getByText("No recovery data stored", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "30 days", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Sleep stages" })).toBeVisible();
  });

  test("sparse activities show recorded metrics without empty feature panels", async ({ page }) => {
    await page.route("**/api/v1/activities/999**", async route => {
      const path = new URL(route.request().url()).pathname;
      const data = path.endsWith("/999") ? { id: 999, name: "Simple walk", sport: "walk", sources: [], distance_m: 2000, duration_s: 1800, has_gps: false, field_provenance: {} }
        : path.endsWith("/analysis") ? { metrics: { trimp: { available: false, unavailable_reason: "Heart rate was not recorded" } }, source_comparison: { available: false, fields: [] } }
        : path.endsWith("/streams") ? { available: false, channels: {}, point_count: 0 }
        : path.endsWith("/zones") ? { available: false, zones: [] } : [];
      await route.fulfill({ json: data });
    });
    await page.goto("/activities/999");
    await expect(page.getByRole("heading", { name: "Simple walk" })).toBeVisible();
    await expect(page.locator(".readout")).toHaveCount(2);
    await expect(page.getByText("Unavailable", { exact: true })).toHaveCount(0);
    for (const title of ["Session charts", "Laps", "Derived analysis", "Best efforts", "Time in heart-rate zones"]) {
      await expect(page.getByRole("heading", { name: title, exact: true })).toHaveCount(0);
    }
    await page.getByText("About data coverage", { exact: true }).click();
    await expect(page.getByText(/Heart rate was not recorded/)).toBeVisible();
  });

  test("the dashboard is usable at a mobile viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.getByRole("navigation", { name: "Sections" }).getByRole("link", { name: "Overview", exact: true })).toBeVisible();
    await expect(page.locator(".vital-value").first()).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
});

/** The page body must never scroll sideways; wide content scrolls in its own box. */
async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const el = document.documentElement;
    return el.scrollWidth - el.clientWidth;
  });
  expect(overflow).toBeLessThanOrEqual(1);
}
