const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const outDir = path.resolve(__dirname, "e2e-theme");
fs.mkdirSync(outDir, { recursive: true });

const localBase = "http://localhost:3001";
const backendBase = "http://localhost:8001";
const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

const themes = ["dark", "light"];
const viewports = {
  desktop: { width: 1365, height: 768 },
  tablet: { width: 820, height: 1180 },
  mobile: { width: 390, height: 844, isMobile: true, hasTouch: true },
};

const routes = [
  "/pcp/dashboard",
  "/pcp/planejamento",
  "/pcp/planejamento?tab=agenda",
  "/pcp/planejamento?tab=config",
  "/pcp/horizonte",
  "/pcp/controle-ops",
  "/pcp/produtos",
  "/pcp/insumos",
  "/pcp/apontamento",
  "/orders",
  "/orders/gerador",
];

function safeName(value) {
  return value.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();
}

function luminance(rgbString) {
  const nums = (rgbString.match(/\d+/g) || []).slice(0, 3).map(Number);
  if (nums.length < 3) return null;
  const [r, g, b] = nums.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

async function createAuditedPage(browser, viewport) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    isMobile: !!viewport.isMobile,
    hasTouch: !!viewport.hasTouch,
  });
  const page = await context.newPage();
  const events = { console: [], pageErrors: [], failedResponses: [], failedRequests: [] };
  page.on("console", (msg) => {
    if (["error", "warning"].includes(msg.type())) events.console.push({ type: msg.type(), text: msg.text().slice(0, 500) });
  });
  page.on("pageerror", (err) => events.pageErrors.push(String(err).slice(0, 500)));
  page.on("response", (res) => {
    const url = res.url();
    if (res.status() >= 400 && !url.includes("favicon") && !url.includes("sockjs-node")) {
      events.failedResponses.push({ status: res.status(), url });
    }
  });
  page.on("requestfailed", (req) => {
    const url = req.url();
    if (!url.includes("favicon") && !url.includes("sockjs-node")) {
      events.failedRequests.push({ url, failure: req.failure()?.errorText || "" });
    }
  });
  return { context, page, events };
}

async function loginWithTheme(page, theme) {
  await page.goto(`${localBase}/login`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.evaluate((themeValue) => {
    localStorage.setItem("theme", themeValue);
    localStorage.removeItem("sidebarCollapsed");
  }, theme);
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.fill("[data-testid='login-email-input']", "admin@kuryos.com");
  await page.fill("[data-testid='login-password-input']", "admin123");
  await Promise.all([
    page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 30000 }),
    page.click("[data-testid='login-submit-btn']"),
  ]);
}

async function collectMetrics(page, expectedTheme) {
  return page.evaluate((expectedThemeValue) => {
    const doc = document.documentElement;
    const body = document.body;
    const bodyText = body.innerText || "";
    const themeClassOk = expectedThemeValue === "dark" ? doc.classList.contains("dark") : !doc.classList.contains("dark");
    const bodyStyles = getComputedStyle(body);
    const main = document.querySelector("main");
    const mainRect = main?.getBoundingClientRect();
    const overflowX = Math.max(0, doc.scrollWidth - window.innerWidth);
    const fixedSidebars = [...document.querySelectorAll("aside, nav")]
      .filter((el) => {
        const rect = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return rect.width > 120 && rect.height > 300 && ["fixed", "sticky"].includes(cs.position) && rect.right > 0 && rect.left < window.innerWidth;
      })
      .map((el) => ({ width: Math.round(el.getBoundingClientRect().width), text: (el.innerText || "").slice(0, 80) }));

    const clipped = [...document.querySelectorAll("button, a, th, td, label, .truncate")]
      .filter((el) => {
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
        const cs = getComputedStyle(el);
        if (cs.display === "none" || cs.visibility === "hidden") return false;
        return el.scrollWidth > el.clientWidth + 4 && !["hidden", "clip"].includes(cs.overflowX);
      })
      .slice(0, 12)
      .map((el) => ({ text: (el.innerText || el.textContent || "").trim().slice(0, 90), tag: el.tagName, width: Math.round(el.getBoundingClientRect().width) }));

    const tinyTapTargets = [...document.querySelectorAll("button, a, input, select")]
      .filter((el) => {
        const rect = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        if (rect.width <= 0 || rect.height <= 0 || cs.display === "none" || cs.visibility === "hidden") return false;
        if (el.closest("table")) return false;
        return rect.width < 28 || rect.height < 28;
      })
      .slice(0, 12)
      .map((el) => ({ text: (el.innerText || el.getAttribute("aria-label") || el.getAttribute("title") || "").trim().slice(0, 80), tag: el.tagName, w: Math.round(el.getBoundingClientRect().width), h: Math.round(el.getBoundingClientRect().height) }));

    const visibleDialogCount = [...document.querySelectorAll('[role="dialog"]')]
      .filter((el) => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }).length;

    return {
      title: document.title,
      bodyChars: bodyText.length,
      themeClassOk,
      bodyBg: bodyStyles.backgroundColor,
      bodyColor: bodyStyles.color,
      mainVisible: !!mainRect && mainRect.width > 100 && mainRect.height > 100,
      overflowX,
      fixedSidebars,
      clipped,
      tinyTapTargets,
      visibleDialogCount,
      hasKuryos: bodyText.includes("KURYOS"),
      hasPcpOrOrders: /PCP|Pedido|Gerador|Linha|OP|Planejamento|Produ[cç][aã]o/i.test(bodyText),
    };
  }, expectedTheme);
}

async function auditRoute(browser, route, viewportName, theme) {
  const viewport = viewports[viewportName];
  const { context, page, events } = await createAuditedPage(browser, viewport);
  await loginWithTheme(page, theme);
  await page.goto(`${localBase}${route}`, { waitUntil: "networkidle", timeout: 45000 });
  await page.waitForTimeout(800);
  const metrics = await collectMetrics(page, theme);
  const screenshot = path.join(outDir, `${theme}-${viewportName}-${safeName(route)}.png`);
  await page.screenshot({ path: screenshot, fullPage: true });
  await context.close();

  const failures = [];
  if (events.pageErrors.length) failures.push(`pageerror: ${events.pageErrors.join(" | ")}`);
  const apiFailures = events.failedResponses.filter((r) => {
    if (!r.url.includes("/api/")) return false;
    if (r.status === 401 && r.url.includes("/api/auth/me")) return false;
    return true;
  });
  if (apiFailures.length) failures.push(`api failures: ${JSON.stringify(apiFailures.slice(0, 5))}`);
  const hardRequestFailures = events.failedRequests.filter((r) => !r.url.includes("localhost:3001/ws"));
  if (hardRequestFailures.length) failures.push(`request failures: ${JSON.stringify(hardRequestFailures.slice(0, 5))}`);
  if (!metrics.themeClassOk) failures.push(`tema ${theme} nao aplicado`);
  if (!metrics.mainVisible) failures.push("conteudo principal nao visivel");
  if (metrics.bodyChars < 150) failures.push("conteudo insuficiente");
  if (!metrics.hasPcpOrOrders) failures.push("conteudo PCP/Pedidos nao detectado");
  if (metrics.overflowX > (viewportName === "desktop" ? 4 : 8)) failures.push(`overflow horizontal ${metrics.overflowX}px`);
  if (viewportName === "desktop" && metrics.fixedSidebars.length > 1) failures.push(`sidebars duplicadas: ${metrics.fixedSidebars.length}`);
  if (metrics.visibleDialogCount > 0) failures.push("dialog aberto inesperado");
  if (metrics.clipped.length) failures.push(`texto estourando: ${JSON.stringify(metrics.clipped.slice(0, 4))}`);
  if (viewportName !== "desktop" && metrics.tinyTapTargets.length) failures.push(`alvos pequenos: ${JSON.stringify(metrics.tinyTapTargets.slice(0, 4))}`);

  return { route, viewport: viewportName, theme, metrics, events, screenshot, failures };
}

async function auditThemeToggle(browser, viewportName) {
  const viewport = viewports[viewportName];
  const { context, page } = await createAuditedPage(browser, viewport);
  await loginWithTheme(page, "dark");
  await page.goto(`${localBase}/pcp/dashboard`, { waitUntil: "networkidle", timeout: 45000 });
  await page.waitForTimeout(500);

  if (viewportName === "mobile") {
    await page.click("[data-testid='mobile-menu-btn']");
    await page.waitForTimeout(300);
    await page.locator("[data-testid='mobile-sidebar-drawer'] [data-testid='theme-toggle']").click();
  } else {
    await page.locator("[data-testid='sidebar'] [data-testid='theme-toggle']").click();
  }
  await page.waitForTimeout(500);
  const afterLight = await collectMetrics(page, "light");

  if (viewportName === "mobile") {
    if (!(await page.locator("[data-testid='mobile-sidebar-drawer']").count())) await page.click("[data-testid='mobile-menu-btn']");
    await page.locator("[data-testid='mobile-sidebar-drawer'] [data-testid='theme-toggle']").click();
  } else {
    await page.locator("[data-testid='sidebar'] [data-testid='theme-toggle']").click();
  }
  await page.waitForTimeout(500);
  const afterDark = await collectMetrics(page, "dark");
  const screenshot = path.join(outDir, `toggle-${viewportName}.png`);
  await page.screenshot({ path: screenshot, fullPage: true });
  await context.close();

  const failures = [];
  if (!afterLight.themeClassOk) failures.push("toggle para claro falhou");
  if (!afterDark.themeClassOk) failures.push("toggle para escuro falhou");
  return { route: "theme-toggle", viewport: viewportName, theme: "toggle", metrics: { afterLight, afterDark }, screenshot, failures };
}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: fs.existsSync(chromePath) ? chromePath : undefined,
  });

  const results = [];
  for (const theme of themes) {
    for (const viewportName of Object.keys(viewports)) {
      for (const route of routes) {
        results.push(await auditRoute(browser, route, viewportName, theme));
      }
    }
  }
  for (const viewportName of Object.keys(viewports)) {
    results.push(await auditThemeToggle(browser, viewportName));
  }
  await browser.close();

  const reportPath = path.join(outDir, "report.json");
  fs.writeFileSync(reportPath, JSON.stringify(results, null, 2));
  const failures = results.flatMap((result) => (result.failures || []).map((failure) => ({
    route: result.route,
    viewport: result.viewport,
    theme: result.theme,
    failure,
    screenshot: result.screenshot,
  })));

  const themeLum = results
    .filter((r) => routes.includes(r.route))
    .slice(0, 6)
    .map((r) => ({ theme: r.theme, viewport: r.viewport, route: r.route, bgLum: luminance(r.metrics.bodyBg), colorLum: luminance(r.metrics.bodyColor) }));

  console.log(JSON.stringify({ reportPath, checked: results.length, failures, sampleThemeLuminance: themeLum }, null, 2));
  if (failures.length) process.exit(1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
