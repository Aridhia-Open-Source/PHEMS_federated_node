// Screenshots of the core admin screens in dark mode, for design review.
// Read-only: it logs in and looks; it never submits a form or confirms a delete.
//
//   npm run screenshots
//
// UI_URL       where the UI is served (default: the Tilt dev cluster)
// FN_USER      login name (default: KEYCLOAK_FIRST_USER_EMAIL from the repo's .dev.env)
// FN_PASSWORD  its password (default: KEYCLOAK_FIRST_USER_PASSWORD from .dev.env)
// OUT_DIR      where the PNGs go (default: ~/nexus-ui-screenshots/<today>)
//
// Pages come from the side menu and the links on each page, so a new page in routes.tsx
// shows up here by itself. The project shown is the first one with a resource to open.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 };
// Same key as src/shell/theme.ts; the inline script in index.html applies it before paint
const THEME_KEY = "fn-theme";

const UI_URL = (process.env.UI_URL ?? "http://localhost:8088/nexus-ui/").replace(/\/*$/, "/");
const OUT_DIR =
  process.env.OUT_DIR ??
  path.join(os.homedir(), "nexus-ui-screenshots", new Date().toLocaleDateString("sv-SE"));

function devEnv() {
  const file = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../.dev.env");
  if (!fs.existsSync(file)) return {};
  const pairs = fs
    .readFileSync(file, "utf8")
    .split("\n")
    .map((line) => line.match(/^\s*([A-Z0-9_]+)=(.*)$/))
    .filter(Boolean)
    .map(([, key, value]) => [key, value.trim().replace(/^(["'])(.*)\1$/, "$2")]);
  return Object.fromEntries(pairs);
}

const env = devEnv();
const USER = process.env.FN_USER ?? env.KEYCLOAK_FIRST_USER_EMAIL;
const PASSWORD = process.env.FN_PASSWORD ?? env.KEYCLOAK_FIRST_USER_PASSWORD;
if (!USER || !PASSWORD) {
  throw new Error("Set FN_USER and FN_PASSWORD (no KEYCLOAK_FIRST_USER_* found in the repo .dev.env)");
}

const href = (h) => new URL(h, UI_URL).href;
const slugify = (text) => text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const lastSegment = (h) => h.replace(/\/+$/, "").split("/").pop();

/** Waits until the page has stopped fetching and its loading star is gone. */
async function settle(page) {
  await page.waitForLoadState("networkidle");
  await page.waitForFunction(() => !document.querySelector('main [data-slot="loading-star"]'));
}

async function visit(page, url) {
  await page.goto(url);
  await settle(page);
}

async function login(page) {
  await page.fill("#username", USER);
  await page.fill("#password", PASSWORD);
  await page.click("button[type=submit]");
  await page
    .getByRole("button", { name: "Open menu" })
    .waitFor({ timeout: 15_000 })
    .catch(() => {
      throw new Error(`Login as ${USER} did not reach the app`);
    });
  await settle(page);
}

async function newContext(browser, viewport) {
  const context = await browser.newContext({ viewport, colorScheme: "dark" });
  await context.addInitScript((key) => localStorage.setItem(key, "dark"), THEME_KEY);
  return context;
}

const linksIn = (page, selector) =>
  page.locator(selector).evaluateAll((as) => as.map((a) => a.getAttribute("href")));

const menuLinks = (page) =>
  page.locator("[role=dialog] a").evaluateAll((as) =>
    as.map((a) => ({ href: a.getAttribute("href"), label: a.textContent.trim() })),
  );

async function openMenu(page) {
  await page.getByRole("button", { name: "Open menu" }).click();
  await page.locator("[role=dialog]").waitFor();
}

/** The first link in the page body that points below `base`, e.g. a row's detail page. */
async function firstBelow(page, base) {
  return (await linksIn(page, `main a[href^="${base}/"]`))[0];
}

/**
 * The project tabs, each followed by the first thing to open in it (a resource, a
 * repository and its first pull request, a task, a result). A project with nothing in it
 * only gets the tabs.
 */
async function projectSteps(page, projectHref) {
  await visit(page, href(projectHref));
  const tabs = await linksIn(page, "main nav a");
  const steps = [];
  for (const tab of tabs) {
    const name = tab === projectHref ? "overview" : lastSegment(tab);
    steps.push({ slug: `project-${name}`, url: href(tab) });
    if (tab === projectHref) continue;
    await visit(page, href(tab));
    const detail = await firstBelow(page, tab);
    if (!detail) continue;
    steps.push({ slug: `project-${name}-detail`, url: href(detail) });
    await visit(page, href(detail));
    const subdetail = await firstBelow(page, detail);
    if (subdetail) steps.push({ slug: `project-${name}-subdetail`, url: href(subdetail) });
  }
  return steps;
}

/** The first project that has a resource to open, else the first project. */
async function pickProject(page, projectsHref) {
  await visit(page, href(projectsHref));
  const projects = (await linksIn(page, "main table a")).filter((h) => /\/projects\/\d+$/.test(h));
  for (const project of projects) {
    await visit(page, href(`${project}/resources`));
    if (await firstBelow(page, `${project}/resources`)) return project;
  }
  return projects[0];
}

/** The projects list, its create form and delete dialog, then the project's pages. */
async function projectsSteps(page, projectsHref) {
  await visit(page, href(projectsHref));
  const steps = [{ slug: "projects", url: href(projectsHref) }];

  const create = (await linksIn(page, "main a")).find((h) => h.endsWith("/new"));
  if (create) steps.push({ slug: "projects-new-form", url: href(create) });

  const remove = page.locator("main").getByRole("button", { name: "Delete" }).first();
  if ((await remove.count()) > 0) {
    steps.push({
      slug: "projects-delete-dialog",
      url: href(projectsHref),
      // Opens the dialog and closes it again with Cancel; the confirm button is never touched.
      open: async (p) => {
        await p.locator("main").getByRole("button", { name: "Delete" }).first().click();
        await p.getByRole("alertdialog").waitFor();
      },
      close: (p) => p.getByRole("alertdialog").getByRole("button", { name: "Cancel" }).click(),
    });
  }

  const project = await pickProject(page, projectsHref);
  if (project) steps.push(...(await projectSteps(page, project)));
  else console.log("No projects: only the empty project list is captured");
  return steps;
}

/** Logs in once and walks the side menu, in menu order. */
async function discover(browser) {
  const context = await newContext(browser, DESKTOP);
  const page = await context.newPage();
  await page.goto(UI_URL);
  await login(page);
  await openMenu(page);
  const menu = await menuLinks(page);
  await page.keyboard.press("Escape");

  const steps = [];
  for (const item of menu) {
    if (item.href.endsWith("/projects")) steps.push(...(await projectsSteps(page, item.href)));
    else steps.push({ slug: slugify(item.label), url: href(item.href) });
  }
  await context.close();
  return { menu, steps };
}

async function shot(page, number, slug) {
  const file = path.join(OUT_DIR, `${String(number).padStart(2, "0")}-${slug}.png`);
  await page.screenshot({ path: file, fullPage: true, animations: "disabled" });
  console.log(file);
}

async function captureDesktop(browser, steps, failures) {
  const context = await newContext(browser, DESKTOP);
  const page = await context.newPage();
  await page.goto(UI_URL);
  await settle(page);
  const applied = await page.evaluate(() => document.documentElement.classList.contains("dark"));
  if (!applied) throw new Error("The dark theme did not apply");
  await shot(page, 1, "login");
  await login(page);

  for (const [i, step] of steps.entries()) {
    try {
      await visit(page, step.url);
      await step.open?.(page);
      await shot(page, i + 2, step.slug);
      await step.close?.(page);
    } catch (err) {
      failures.push(`${step.slug}: ${err.message.split("\n")[0]}`);
    }
  }
  await context.close();
}

/** One narrow screen: the first menu page with the side menu open. */
async function captureMobile(browser, menu, number, failures) {
  const context = await newContext(browser, MOBILE);
  const page = await context.newPage();
  await page.goto(UI_URL);
  await login(page);
  try {
    await visit(page, href(menu[0].href));
    await openMenu(page);
    await shot(page, number, `mobile-${slugify(menu[0].label)}-menu-open`);
  } catch (err) {
    failures.push(`mobile: ${err.message.split("\n")[0]}`);
  }
  await context.close();
}

fs.mkdirSync(OUT_DIR, { recursive: true });
const browser = await chromium.launch();
const failures = [];
try {
  const { menu, steps } = await discover(browser);
  await captureDesktop(browser, steps, failures);
  await captureMobile(browser, menu, steps.length + 2, failures);
} finally {
  await browser.close();
}
if (failures.length > 0) {
  console.error(`\nFailed:\n${failures.join("\n")}`);
  process.exitCode = 1;
}
