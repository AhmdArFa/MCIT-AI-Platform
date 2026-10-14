// Builds a .pptx from a Studio deck spec with PptxGenJS.
// Usage: node build_deck.mjs <spec.json> <out.pptx>
// The backend then hands the file to DeckCraft for validation, thumbnails
// and the PDF copy.
import { readFileSync } from "node:fs";
import pptxgen from "pptxgenjs";

const [, , specPath, outPath] = process.argv;
const spec = JSON.parse(readFileSync(specPath, "utf-8"));
const t = spec.theme; // { bg, surface, border, text, muted, accent, accentText, fontHead, fontBody }

const pptx = new pptxgen();
pptx.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pptx.author = spec.author || "MCIT AI";
pptx.company = "Ministry of Communications and Information Technology";
pptx.title = spec.title;

const W = 13.333;
const M = 0.7;
const head = { fontFace: t.fontHead, color: t.text, bold: true };
const body = { fontFace: t.fontBody, color: t.text };
const muted = { fontFace: t.fontBody, color: t.muted };

pptx.defineSlideMaster({
  title: "MCIT",
  background: { color: t.bg },
  objects: [
    { rect: { x: M, y: 7.02, w: W - 2 * M, h: 0.01, fill: { color: t.border } } },
    { text: { text: spec.footer || "MCIT AI", options: { x: M, y: 7.08, w: 8, h: 0.3, fontSize: 9, ...muted } } },
  ],
  slideNumber: { x: W - M - 0.6, y: 7.08, w: 0.6, h: 0.3, fontSize: 9, color: t.muted, align: "right" },
});

function title(slide, text, sub) {
  slide.addShape(pptx.ShapeType.rect, { x: M, y: 0.62, w: 0.08, h: 0.62, fill: { color: t.accent }, line: { color: t.accent } });
  slide.addText(text, { x: M + 0.25, y: 0.5, w: W - 2 * M - 0.25, h: 0.85, fontSize: 28, ...head });
  if (sub) slide.addText(sub, { x: M + 0.25, y: 1.3, w: W - 2 * M - 0.25, h: 0.4, fontSize: 14, ...muted });
}

function bullets(items, opts) {
  return items.map((b) => ({ text: String(b), options: { bullet: { code: "25A0", indent: 18 }, paraSpaceAfter: 10, ...body, ...opts } }));
}

function card(slide, x, y, w, h) {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: t.surface }, line: { color: t.border, width: 0.75 } });
}

// Cover
{
  const s = pptx.addSlide();
  s.background = { color: t.bg };
  s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 0.22, h: 7.5, fill: { color: t.accent }, line: { color: t.accent } });
  s.addText((spec.kicker || "MCIT AI").toUpperCase(), { x: 1.1, y: 2.0, w: 10, h: 0.4, fontSize: 12, charSpacing: 4, color: t.accent, fontFace: t.fontBody, bold: true });
  s.addText(spec.title, { x: 1.1, y: 2.45, w: 11, h: 1.6, fontSize: 44, ...head, valign: "top" });
  if (spec.subtitle) s.addText(spec.subtitle, { x: 1.1, y: 4.15, w: 11, h: 0.8, fontSize: 18, ...muted });
  s.addText(spec.date || "", { x: 1.1, y: 6.4, w: 6, h: 0.4, fontSize: 12, ...muted });
  if (spec.logo) s.addImage({ path: spec.logo, x: W - 2.3, y: 0.6, w: 1.5, h: 1.5, sizing: { type: "contain", w: 1.5, h: 1.5 } });
}

for (const sl of spec.slides) {
  const s = pptx.addSlide({ masterName: "MCIT" });
  const top = sl.subtitle ? 2.0 : 1.7;
  const h = 6.8 - top;
  title(s, sl.title, sl.subtitle);
  switch (sl.layout) {
    case "stats":
    case "cards": {
      const items = sl.layout === "stats" ? sl.stats.map((x) => [x.value, x.label]) : sl.bullets.map((b) => ["", b]);
      const n = Math.max(1, Math.min(items.length, 4));
      const gap = 0.3;
      const cw = (W - 2 * M - gap * (n - 1)) / n;
      items.slice(0, 4).forEach(([v, l], i) => {
        const x = M + i * (cw + gap);
        card(s, x, top + 0.3, cw, 2.6);
        if (v) s.addText(String(v), { x: x + 0.25, y: top + 0.5, w: cw - 0.5, h: 1.1, fontSize: 40, color: t.accent, fontFace: t.fontHead, bold: true });
        s.addText(String(l), { x: x + 0.25, y: v ? top + 1.6 : top + 0.5, w: cw - 0.5, h: v ? 1.1 : 2.2, fontSize: v ? 14 : 16, ...body, valign: "top" });
      });
      if (sl.bullets.length && sl.layout === "stats") s.addText(bullets(sl.bullets.slice(0, 3), { fontSize: 14 }), { x: M, y: top + 3.2, w: W - 2 * M, h: 1.6, valign: "top" });
      break;
    }
    case "two_column":
    case "comparison": {
      const cw = (W - 2 * M - 0.4) / 2;
      [[sl.left_title, sl.left], [sl.right_title, sl.right]].forEach(([ct, items], i) => {
        const x = M + i * (cw + 0.4);
        card(s, x, top, cw, h);
        if (ct) s.addText(ct, { x: x + 0.3, y: top + 0.2, w: cw - 0.6, h: 0.5, fontSize: 18, color: t.accent, fontFace: t.fontHead, bold: true });
        s.addText(bullets(items || [], { fontSize: 15 }), { x: x + 0.3, y: top + 0.8, w: cw - 0.6, h: h - 1.0, valign: "top" });
      });
      break;
    }
    case "process": {
      const steps = (sl.steps.length ? sl.steps : sl.bullets).slice(0, 5);
      const n = Math.max(steps.length, 1);
      const gap = 0.25;
      const cw = (W - 2 * M - gap * (n - 1)) / n;
      steps.forEach((st, i) => {
        const x = M + i * (cw + gap);
        card(s, x, top + 0.4, cw, 2.8);
        s.addText(String(i + 1).padStart(2, "0"), { x: x + 0.25, y: top + 0.55, w: 1, h: 0.6, fontSize: 24, color: t.accent, fontFace: t.fontHead, bold: true });
        s.addText(String(st), { x: x + 0.25, y: top + 1.2, w: cw - 0.5, h: 1.9, fontSize: 14, ...body, valign: "top" });
      });
      break;
    }
    case "quote": {
      card(s, M, top + 0.3, W - 2 * M, 3.2);
      s.addText(`\u201C${sl.quote || sl.bullets[0] || ""}\u201D`, { x: M + 0.6, y: top + 0.5, w: W - 2 * M - 1.2, h: 2.8, fontSize: 26, italic: true, ...body, valign: "middle" });
      break;
    }
    case "chart": {
      if (sl.chart_labels.length && sl.chart_values.length) {
        s.addChart(pptx.ChartType.bar, [{ name: sl.title, labels: sl.chart_labels, values: sl.chart_values }], {
          x: M, y: top, w: W - 2 * M - (sl.bullets.length ? 4.2 : 0), h,
          chartColors: [t.accent], catAxisLabelColor: t.muted, valAxisLabelColor: t.muted,
          valGridLine: { color: t.border, size: 0.5 }, catGridLine: { style: "none" },
          showValue: true, dataLabelColor: t.text, dataLabelFontSize: 11, catAxisLabelFontSize: 11,
        });
      }
      if (sl.bullets.length) s.addText(bullets(sl.bullets, { fontSize: 14 }), { x: W - M - 3.9, y: top, w: 3.9, h, valign: "top" });
      break;
    }
    case "table": {
      const cols = sl.table_columns;
      const rows = [cols.map((c) => ({ text: String(c), options: { bold: true, color: t.accentText, fill: { color: t.accent } } }))];
      for (const r of sl.table_rows.slice(0, 12)) rows.push(r.map((c) => ({ text: String(c ?? ""), options: { color: t.text, fill: { color: t.surface } } })));
      if (cols.length) s.addTable(rows, { x: M, y: top, w: W - 2 * M, fontSize: 12, fontFace: t.fontBody, border: { type: "solid", color: t.border, pt: 0.75 }, autoPage: false });
      break;
    }
    default: {
      s.addText(bullets(sl.bullets, { fontSize: 18 }), { x: M, y: top, w: W - 2 * M, h, valign: "top" });
    }
  }
  if (sl.notes) s.addNotes(sl.notes);
}

// Closing
{
  const s = pptx.addSlide();
  s.background = { color: t.bg };
  s.addText(spec.closing || "Thank you", { x: 1.1, y: 2.9, w: 11, h: 1.2, fontSize: 40, ...head });
  s.addText(spec.footer || "MCIT AI", { x: 1.1, y: 4.1, w: 11, h: 0.5, fontSize: 16, color: t.accent, fontFace: t.fontBody });
}

await pptx.writeFile({ fileName: outPath });
