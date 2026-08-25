/* 画面の実描画を確認するための撮影スクリプト(開発用)。
 * 使い方: node harness/shot.mjs <url> <出力パス> [幅] [高さ] [--dark] [--click-chapter=N]
 * コンソールエラーを標準出力に流す — 描画が黙って壊れるのを見逃さないため。
 */
import { chromium } from "playwright";

const [url, out, w = "1280", h = "1200", ...rest] = process.argv.slice(2);
const dark = rest.includes("--dark");
const clickArg = rest.find((a) => a.startsWith("--click-chapter="));

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: +w, height: +h },
  colorScheme: dark ? "dark" : "light",
  deviceScaleFactor: 2,
});
const problems = [];
page.on("console", (m) => { if (m.type() === "error") problems.push("console: " + m.text()); });
page.on("pageerror", (e) => problems.push("pageerror: " + e.message));
page.on("requestfailed", (r) => problems.push("requestfailed: " + r.url()));

await page.goto(url, { waitUntil: "networkidle" });
if (clickArg) {
  await page.click(`.band-row[data-ch="${clickArg.split("=")[1]}"]`);
  await page.waitForTimeout(300);
}
await page.waitForTimeout(200);
await page.screenshot({ path: out, fullPage: true });
console.log(problems.length ? problems.join("\n") : "問題なし");
await browser.close();
