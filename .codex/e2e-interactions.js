const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const outDir = path.resolve(__dirname, "e2e");
fs.mkdirSync(outDir, { recursive: true });

async function login(page) {
  await page.goto("http://localhost:3001/login", { waitUntil: "domcontentloaded" });
  await page.fill("[data-testid='login-email-input']", "admin@kuryos.com");
  await page.fill("[data-testid='login-password-input']", "admin123");
  await Promise.all([
    page.waitForURL((url) => !url.pathname.includes("/login")),
    page.click("[data-testid='login-submit-btn']"),
  ]);
}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  });
  const failures = [];

  const desktop = await browser.newContext({ viewport: { width: 1365, height: 768 } });
  const page = await desktop.newPage();
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  await login(page);

  await page.goto("http://localhost:3001/pcp/dashboard", { waitUntil: "networkidle" });
  await page.click("[data-testid='sidebar-collapse-btn']");
  await page.waitForTimeout(500);
  const collapsedWidth = await page.locator("[data-testid='sidebar']").evaluate((el) => Math.round(el.getBoundingClientRect().width));
  if (collapsedWidth > 90) failures.push(`sidebar nao minimizou: ${collapsedWidth}px`);
  await page.click("[data-testid='sidebar-expand-btn']");
  await page.waitForTimeout(500);
  const expandedWidth = await page.locator("[data-testid='sidebar']").evaluate((el) => Math.round(el.getBoundingClientRect().width));
  if (expandedWidth < 200) failures.push(`sidebar nao expandiu: ${expandedWidth}px`);

  await page.goto("http://localhost:3001/pcp/controle-ops", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /Recalcular Status/i }).click();
  await page.waitForTimeout(1500);
  if (!(await page.getByText(/OPs Ativas/i).count())) failures.push("controle de OPs nao renderizou apos recalculo");

  await page.goto("http://localhost:3001/orders/gerador", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /Ver pedidos gerados/i }).click();
  await page.waitForTimeout(1000);
  if (!(await page.getByText(/Gerador de Pedidos|Pedidos/i).count())) failures.push("gerador nao respondeu ao botao ver pedidos");

  await page.screenshot({ path: path.join(outDir, "interaction-desktop-final.png"), fullPage: true });
  await desktop.close();

  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const mpage = await mobile.newPage();
  await login(mpage);
  await mpage.goto("http://localhost:3001/pcp/dashboard", { waitUntil: "networkidle" });
  await mpage.click("[data-testid='mobile-menu-btn']");
  await mpage.waitForTimeout(500);
  if (!(await mpage.locator("[data-testid='mobile-sidebar-drawer']").count())) failures.push("menu hamburguer mobile nao abriu");
  await mpage.locator("[data-testid='mobile-sidebar-drawer'] [data-testid='nav-pcp-planejamento']").click();
  await mpage.waitForURL(/pcp\/planejamento/);
  if (await mpage.locator("[data-testid='mobile-sidebar-drawer']").count()) failures.push("menu mobile nao fechou apos navegar");
  const overflow = await mpage.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (overflow > 8) failures.push(`overflow mobile apos navegacao: ${overflow}px`);
  await mpage.screenshot({ path: path.join(outDir, "interaction-mobile-final.png"), fullPage: true });
  await mobile.close();

  await browser.close();
  if (errors.length) failures.push(`page errors: ${errors.join(" | ")}`);
  console.log(JSON.stringify({ failures }, null, 2));
  if (failures.length) process.exit(1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
