const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const outDir = path.resolve(__dirname, "e2e");
fs.mkdirSync(outDir, { recursive: true });

const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const localBase = "http://localhost:3001";
const backendBase = "http://localhost:8001";

const viewports = {
  desktop: { width: 1365, height: 768 },
  mobile: { width: 390, height: 844, isMobile: true },
};

function safeName(value) {
  return value.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "").toLowerCase();
}

async function createPage(browser, viewport) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    isMobile: !!viewport.isMobile,
    hasTouch: !!viewport.isMobile,
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  const events = { console: [], pageErrors: [], failedResponses: [], failedRequests: [] };
  page.on("console", (msg) => {
    if (["error", "warning"].includes(msg.type())) {
      events.console.push({ type: msg.type(), text: msg.text().slice(0, 500) });
    }
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

async function loginLocal(page) {
  await page.goto(`${localBase}/login`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.fill("[data-testid='login-email-input']", "admin@kuryos.com");
  await page.fill("[data-testid='login-password-input']", "admin123");
  await Promise.all([
    page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 30000 }),
    page.click("[data-testid='login-submit-btn']"),
  ]);
}

async function localMetrics(page) {
  return page.evaluate(() => {
    const bodyText = document.body.innerText || "";
    const widthOverflow = Math.max(0, document.documentElement.scrollWidth - window.innerWidth);
    const fixedSidebars = [...document.querySelectorAll("aside, nav")]
      .filter((el) => {
        const cs = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return rect.width > 120 && rect.height > 400 && ["fixed", "sticky"].includes(cs.position);
      })
      .map((el) => ({
        tag: el.tagName,
        width: Math.round(el.getBoundingClientRect().width),
        text: (el.innerText || "").slice(0, 80),
      }));
    const visibleDialogs = [...document.querySelectorAll('[role="dialog"]')]
      .filter((el) => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }).length;
    const clippedText = [...document.querySelectorAll("button, th, td, .truncate")]
      .filter((el) => el.scrollWidth > el.clientWidth + 2 && getComputedStyle(el).overflow === "visible")
      .slice(0, 10)
      .map((el) => (el.innerText || el.textContent || "").trim().slice(0, 80));
    return {
      title: document.title,
      bodyChars: bodyText.length,
      widthOverflow,
      fixedSidebars,
      visibleDialogs,
      clippedText,
      hasKuryos: bodyText.includes("KURYOS"),
      hasPcp: /PCP|Linha|OP|Planejamento|Produ[cç][aã]o/i.test(bodyText),
      hasGerador: /Gerador|Pedido|Cliente|Itens/i.test(bodyText),
    };
  });
}

async function auditLocalRoute(browser, route, viewportName) {
  const viewport = viewports[viewportName];
  const { context, page, events } = await createPage(browser, viewport);
  await loginLocal(page);
  await page.goto(`${localBase}${route}`, { waitUntil: "networkidle", timeout: 45000 });
  await page.waitForTimeout(1000);
  const metrics = await localMetrics(page);
  const screenshot = path.join(outDir, `${viewportName}-local-${safeName(route)}.png`);
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
  if (events.failedRequests.some((r) => !r.url.includes("localhost:3001/ws"))) failures.push(`request failures: ${JSON.stringify(events.failedRequests.slice(0, 5))}`);
  if (metrics.bodyChars < 150) failures.push("body vazio ou rota nao renderizada");
  if (metrics.widthOverflow > (viewportName === "mobile" ? 8 : 4)) failures.push(`overflow horizontal ${metrics.widthOverflow}px`);
  if (viewportName === "desktop" && metrics.fixedSidebars.length > 1) failures.push(`sidebars fixas duplicadas: ${metrics.fixedSidebars.length}`);
  if (metrics.visibleDialogs > 0) failures.push("dialog aberto inesperadamente");
  if (route.includes("/pcp") && !metrics.hasPcp) failures.push("conteudo PCP nao detectado");
  if (route.includes("/orders") && !metrics.hasGerador) failures.push("conteudo de pedidos/gerador nao detectado");

  return { kind: "local", route, viewport: viewportName, metrics, events, screenshot, failures };
}

async function auditRemoteGenerator(browser, viewportName) {
  const viewport = viewports[viewportName];
  const { context, page, events } = await createPage(browser, viewport);
  await page.setExtraHTTPHeaders({
    Authorization: `Basic ${Buffer.from("kuryos:Kuryos@123").toString("base64")}`,
  });
  await page.goto("https://gerador-pedidos-a8wm.onrender.com/", { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(2500);
  const body = await page.locator("body").innerText().catch(() => "");
  const screenshot = path.join(outDir, `${viewportName}-ref-gerador.png`);
  await page.screenshot({ path: screenshot, fullPage: true });
  await context.close();
  return {
    kind: "reference",
    route: "gerador",
    viewport: viewportName,
    bodyChars: body.length,
    hasExpected: /Gerador de Pedidos|Cliente|Itens do Pedido|Revisar Pedido/i.test(body),
    events,
    screenshot,
  };
}

async function auditRemotePcp(browser, viewportName) {
  const viewport = viewports[viewportName];
  const { context, page, events } = await createPage(browser, viewport);
  await page.goto("https://prod-kuryos.web.app/dashboard.html", { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(1500);
  const email = page.locator("input[type='email'], input[name='email']").first();
  if (await email.count()) {
    await email.fill("gustavo@kuryos.com.br");
    await page.locator("input[type='password'], input[name='password']").first().fill("Kuryos@123");
    const submit = page.locator("button:has-text('Entrar no Sistema'), button[type='submit']").first();
    await submit.click();
    await page.waitForTimeout(7000);
  }
  const body = await page.locator("body").innerText().catch(() => "");
  const screenshot = path.join(outDir, `${viewportName}-ref-pcp-dashboard.png`);
  await page.screenshot({ path: screenshot, fullPage: true });
  await context.close();
  return {
    kind: "reference",
    route: "pcp-dashboard",
    viewport: viewportName,
    bodyChars: body.length,
    hasExpected: /Dashboard|PCP|Linha|Produ[cç][aã]o|Planejamento/i.test(body),
    events,
    screenshot,
  };
}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: fs.existsSync(chromePath) ? chromePath : undefined,
  });

  const results = [];
  for (const viewportName of Object.keys(viewports)) {
    results.push(await auditRemoteGenerator(browser, viewportName));
    results.push(await auditRemotePcp(browser, viewportName));
  }

  const localRoutes = [
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
  for (const viewportName of Object.keys(viewports)) {
    for (const route of localRoutes) {
      results.push(await auditLocalRoute(browser, route, viewportName));
    }
  }
  await browser.close();

  const reportPath = path.join(outDir, "report.json");
  fs.writeFileSync(reportPath, JSON.stringify(results, null, 2));
  const failures = results.flatMap((result) => (result.failures || []).map((failure) => ({ route: result.route, viewport: result.viewport, failure })));
  console.log(JSON.stringify({ reportPath, failures, count: results.length }, null, 2));
  if (failures.length) process.exit(1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
