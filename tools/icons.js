// Tegner PNG-ikoner ud fra SVG-kilderne i hub/static (kræver playwright: npm i -D playwright).
// Brug: node tools/icons.js     Resultatet lægges i hub/static og docs/assets.
const fs = require("fs"), path = require("path");
const { chromium } = require("playwright");
const root = path.join(__dirname, "..");
const st = path.join(root, "hub", "static"), out2 = path.join(root, "docs", "assets");
fs.mkdirSync(out2, { recursive: true });
const svg = (f) => fs.readFileSync(path.join(st, f), "utf8");
const jobs = [
  ["logo.svg", 512, "icon-512.png", true], ["logo.svg", 192, "icon-192.png", true],
  ["icon-full.svg", 512, "icon-maskable-512.png", false],      // helt til kanten: telefonen beskærer selv
  ["icon-full.svg", 180, "apple-touch-icon.png", false],       // iOS runder selv hjørnerne
  ["logo.svg", 64, "favicon-64.png", true], ["logo.svg", 32, "favicon-32.png", true],
];
(async () => {
  const b = await chromium.launch(); const p = await b.newPage();
  for (const [src, size, name, transparent] of jobs) {
    await p.setViewportSize({ width: size, height: size });
    await p.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:${size}px;height:${size}px}</style>${svg(src)}`);
    const buf = await p.screenshot({ omitBackground: transparent, clip: { x: 0, y: 0, width: size, height: size } });
    fs.writeFileSync(path.join(st, name), buf); fs.writeFileSync(path.join(out2, name), buf);
  }
  await b.close();
  for (const f of ["logo.svg", "favicon.svg", "mark.svg"]) fs.copyFileSync(path.join(st, f), path.join(out2, f));
  console.log("ikoner skrevet");
})();
