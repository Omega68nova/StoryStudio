import { expect, test } from "@playwright/test";

const sizes = [{ width: 1024, height: 720 }, { width: 1280, height: 720 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 }];

for (const viewport of sizes) test(`desktop controls remain reachable at ${viewport.width}x${viewport.height}`, async ({ page }) => {
  await page.setViewportSize(viewport);
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const project = { id: "p1", title: "Viewport Story", active_node_id: "a1", created_at: "2026-01-01", updated_at: "2026-01-01",
      bible_documents: ["Premise", "Style", "World", "Characters", "Continuity"].map((title, i) => ({ id: `b${i}`, project_id: "p1", kind: title.toLowerCase(), title, content: "", position: i })),
      story_nodes: [{ id: "u1", project_id: "p1", parent_id: null, role: "user", content: "Begin", status: "complete", created_at: "2026-01-01", action_kind: "do" }, { id: "a1", project_id: "p1", parent_id: "u1", role: "assistant", content: "The road opens ahead. The party follows it beyond the old boundary stones.\n\n".repeat(50), status: "complete", created_at: "2026-01-01" }],
      trashed_story_nodes: [], suggestions: [{ id: "s1", story_node_id: "a1", title: "Hidden controls", prompt: "A generated scene", negative_prompt: "", status: "generated", image_path: "images/generated.png" }], npc_interventions: [], scene_appearances: [] };
    let body: unknown = {};
    if (path === "/api/projects") body = [{ id: "p1", title: "Viewport Story", active_node_id: "a1", created_at: "2026-01-01", updated_at: "2026-01-01" }];
    else if (path === "/api/projects/p1") body = project;
    else if (path === "/api/workflows") body = [];
    else if (path === "/api/version") body = { version: "0.5.0-fast-streaming" };
    else if (path === "/api/session") body = { websocket_token: "test" };
    else if (path === "/api/jobs") body = [];
    else if (path === "/api/projects/p1/entities") body = [];
    else if (path === "/api/projects/p1/reviews") body = [];
    else if (path.endsWith("/world")) body = { project_id: "p1", head_node_id: "a1", entities: {}, relations: {}, elapsed_minutes: 0, display_time: null, transactions: [] };
    else if (path.endsWith("/reviews")) body = [];
    else if (path.endsWith("/rules")) body = { stats: [], abilities: [] };
    else if (path === "/api/music/themes") body = [{ id: "t1", name: "Ruins", description: "", playback_mode: "shuffle", tracks: [] }];
    else if (path.endsWith("/music")) body = { project_id: "p1", mode: "player_managed", manual_theme_id: "t1", current_theme_id: null, volume: .7, enabled_theme_ids: ["t1"] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Viewport Story" })).toBeVisible();
  const stage = await page.locator(".stage").boundingBox();
  const storyHeader = await page.locator(".app-topbar").boundingBox();
  const composer = await page.locator(".composer").boundingBox();
  const player = await page.locator(".music-player-rnd").boundingBox();
  expect(stage && composer && player).toBeTruthy();
  expect(storyHeader!.height).toBeLessThanOrEqual(45);
  expect(composer!.y + composer!.height).toBeLessThanOrEqual(stage!.y + stage!.height + 1);
  const transcript = page.locator(".transcript");
  await expect.poll(() => transcript.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
  await transcript.evaluate((element) => { element.scrollTop = 0; });
  await expect.poll(() => transcript.evaluate((element) => element.scrollTop)).toBe(0);
  await transcript.evaluate((element) => { element.scrollTop = element.scrollHeight; });
  await expect.poll(() => transcript.evaluate((element) => Math.ceil(element.scrollTop + element.clientHeight) >= element.scrollHeight)).toBe(true);
  expect(player!.x).toBeGreaterThanOrEqual(stage!.x);
  expect(player!.x + player!.width).toBeLessThanOrEqual(viewport.width + 1);
  expect(player!.y + player!.height).toBeLessThanOrEqual(composer!.y + 1);
  const projectSelect = await page.locator(".project-select").boundingBox();
  const projectDelete = await page.getByRole("button", { name: "Delete story" }).boundingBox();
  expect(projectSelect!.width).toBeGreaterThan(projectDelete!.width * 2);
  expect(projectDelete!.width).toBeLessThanOrEqual(40);
  await expect(page.locator(".suggestion-card.generated")).toHaveCount(1);
  await expect(page.locator(".suggestion-card.generated").getByText("Illustration idea")).toHaveCount(0);
  await expect(page.locator(".suggestion-card.generated select")).toHaveCount(0);
  await page.getByRole("button", { name: /Branches/ }).click();
  await expect(page.getByRole("heading", { name: "Branches" })).toBeVisible();
  await expect(page.locator(".MuiDrawer-paper").getByText("Begin", { exact: true })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: "Branches" })).toBeHidden();
  await page.getByRole("button", { name: "Open operation center" }).click();
  await expect(page.getByRole("heading", { name: "Operations" })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Hide stories" }).click();
  await expect(page.locator(".rail")).toBeHidden();
  await expect(page.getByRole("button", { name: "Show stories" })).toBeVisible();
  await page.getByRole("button", { name: "Open workspaces and settings" }).click();
  await page.getByRole("menuitem", { name: "World" }).click();
  await expect(page.locator(".app-topbar")).toBeVisible();
  await expect(page.locator(".app-topbar").getByText("World", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Undo" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Branches for current action/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Open workspaces and settings" }).click();
  await page.getByRole("menuitem", { name: "Story", exact: true }).click();
  await expect(page.getByRole("button", { name: "Undo" })).toBeVisible();
  await page.getByRole("button", { name: "Minimize", exact: true }).click();
  await page.getByRole("button", { name: "Open music player" }).click();
  await expect(page.locator(".music-player-body")).toBeVisible();
});

test("composer minimizes, preserves its draft, restores focus, and remembers its global state", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const project = { id: "p1", title: "Composer Story", active_node_id: null, created_at: "2026-01-01", updated_at: "2026-01-01",
      bible_documents: ["Premise", "Style", "World", "Characters", "Continuity"].map((title, i) => ({ id: `b${i}`, project_id: "p1", kind: title.toLowerCase(), title, content: "", position: i })),
      story_nodes: [], trashed_story_nodes: [], suggestions: [], npc_interventions: [], scene_appearances: [] };
    let body: unknown = {};
    if (path === "/api/projects") body = [{ id: "p1", title: "Composer Story", active_node_id: null, created_at: "2026-01-01", updated_at: "2026-01-01" }];
    else if (path === "/api/projects/p1") body = project;
    else if (path === "/api/workflows" || path.endsWith("/entities") || path.endsWith("/reviews") || path === "/api/jobs" || path === "/api/music/themes") body = [];
    else if (path === "/api/version") body = { version: "0.5.0-fast-streaming" };
    else if (path === "/api/session") body = { websocket_token: "test" };
    else if (path.endsWith("/world")) body = { project_id: "p1", head_node_id: null, entities: {}, relations: {}, elapsed_minutes: 0, display_time: null, transactions: [] };
    else if (path.endsWith("/rules")) body = { stats: [], abilities: [] };
    else if (path.endsWith("/music")) body = { project_id: "p1", mode: "disabled", manual_theme_id: null, current_theme_id: null, volume: .7, enabled_theme_ids: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/");
  const input = page.locator(".composer textarea");
  await input.fill("Keep this unfinished thought");
  await page.getByRole("button", { name: "say", exact: true }).click();
  await page.getByRole("button", { name: "Minimize story input" }).click();
  await expect(page.locator(".composer")).toBeHidden();
  await expect(page.getByRole("button", { name: "Open story input" })).toBeVisible();
  await page.getByRole("button", { name: "Open story input" }).click();
  await expect(input).toHaveValue("Keep this unfinished thought");
  await expect(page.getByRole("button", { name: "say", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(input).toBeFocused();
  await page.getByRole("button", { name: "Minimize story input" }).click();
  await page.reload();
  await expect(page.getByRole("button", { name: "Open story input" })).toBeVisible();
});

test("phone story layout and empty-submit continuation remain usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let submitted: Record<string, unknown> | null = null;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const project = { id: "p1", title: "Pocket Story", active_node_id: null, created_at: "2026-01-01", updated_at: "2026-01-01",
      bible_documents: ["Premise", "Style", "World", "Characters", "Continuity"].map((title, i) => ({ id: `b${i}`, project_id: "p1", kind: title.toLowerCase(), title, content: "Mobile notes", position: i })),
      story_nodes: [], trashed_story_nodes: [], suggestions: [], npc_interventions: [], scene_appearances: [] };
    let body: unknown = {};
    if (path === "/api/projects" && route.request().method() === "GET") body = [{ id: "p1", title: "Pocket Story", active_node_id: null, created_at: "2026-01-01", updated_at: "2026-01-01" }];
    else if (path === "/api/projects/p1") body = project;
    else if (path === "/api/projects/p1/turns") { submitted = route.request().postDataJSON(); body = { user_node: null, job: { id: "j1" } }; }
    else if (path === "/api/workflows" || path.endsWith("/entities") || path.endsWith("/reviews") || path === "/api/jobs" || path === "/api/music/themes") body = [];
    else if (path === "/api/version") body = { version: "0.5.0-fast-streaming" };
    else if (path === "/api/session") body = { websocket_token: "test" };
    else if (path.endsWith("/world")) body = { project_id: "p1", head_node_id: null, entities: {}, relations: {}, elapsed_minutes: 0, display_time: null, transactions: [] };
    else if (path.endsWith("/rules")) body = { stats: [], abilities: [] };
    else if (path.endsWith("/music")) body = { project_id: "p1", mode: "disabled", manual_theme_id: null, current_theme_id: null, volume: .7, enabled_theme_ids: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/");
  await expect(page.locator(".rail")).toBeHidden();
  await expect(page.getByRole("button", { name: "Continue story" })).toBeEnabled();
  await page.getByRole("button", { name: "Continue story" }).click();
  await expect.poll(() => submitted).toMatchObject({ action: "continue", content: "" });
  await page.getByRole("button", { name: "Show stories" }).click();
  await expect(page.locator(".rail")).toBeVisible();
  const rail = await page.locator(".rail").boundingBox();
  expect(rail!.width).toBeLessThan(390);
  await page.getByRole("button", { name: "Hide stories" }).click();
  await page.getByRole("button", { name: "Show story bible" }).click();
  await expect(page.locator(".bible-panel")).toBeVisible();
  const bible = await page.locator(".bible-panel").boundingBox();
  expect(bible!.x).toBeGreaterThanOrEqual(0);
  expect(bible!.x + bible!.width).toBeLessThanOrEqual(391);
});
