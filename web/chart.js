/* 小さな SVG チャートの共通部品。
 *
 * 規律(dataviz):
 *  - 細い罫・目盛りは surface から一段だけ離す。データ点の色は同一性にだけ使う
 *  - 章は 11 あるので**色で符号化しない**(順序ランプは 10 段で隣接 ΔL が不足して不合格)。
 *    同一性は直接ラベル(章番号)が担い、色は「選択中かどうか」だけを表す
 *  - どの図にも表ビューの双子を置く。値は色だけに依存しない
 */

export const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
export const fmt = (n, d = 0) => Number(n).toLocaleString("ja-JP", { maximumFractionDigits: d, minimumFractionDigits: d });

export function el(tag, attrs = {}, children = []) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, v);
  for (const c of [].concat(children)) n.append(c);
  return n;
}

export function svg(width, height, cls = "") {
  const s = el("svg", { viewBox: `0 0 ${width} ${height}`, width: "100%", height,
    role: "img", class: cls, "preserveAspectRatio": "xMidYMid meet" });
  return s;
}

export function axisX(g, x0, x1, y, ticks, label = (v) => v) {
  g.append(el("line", { x1: x0, x2: x1, y1: y, y2: y, stroke: css("--axis"), "stroke-width": 1 }));
  for (const t of ticks) {
    g.append(el("line", { x1: t.x, x2: t.x, y1: y, y2: y + 4, stroke: css("--axis") }));
    const tx = el("text", { x: t.x, y: y + 16, "text-anchor": "middle", "font-size": 10,
      fill: css("--ink-muted") });
    tx.textContent = label(t.v);
    g.append(tx);
  }
}

export function axisY(g, x, y0, y1, ticks, label = (v) => v) {
  for (const t of ticks) {
    g.append(el("line", { x1: x, x2: x + 4, y1: t.y, y2: t.y, stroke: css("--axis") }));
    g.append(el("line", { x1: x + 4, x2: x + 4 + t.w, y1: t.y, y2: t.y,
      stroke: css("--rule"), "stroke-width": 1 }));
    const tx = el("text", { x: x - 6, y: t.y + 3, "text-anchor": "end", "font-size": 10,
      fill: css("--ink-muted") });
    tx.textContent = label(t.v);
    g.append(tx);
  }
  g.append(el("line", { x1: x, x2: x, y1: y0, y2: y1, stroke: css("--axis") }));
}

export function niceTicks(min, max, n = 5) {
  const span = max - min || 1;
  const raw = span / n;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || mag * 10;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

/** hover と focus で同じ内容を出す読み取り欄(ツールチップに値を閉じ込めない) */
export function readout(id) {
  const node = document.getElementById(id);
  return (msg) => { if (node) node.textContent = msg || ""; };
}

export function table(host, headers, rows, caption) {
  const h = `<thead><tr>${headers.map((x) => `<th>${x}</th>`).join("")}</tr></thead>`;
  const b = `<tbody>${rows.map((r) => `<tr>${r.map((x) => `<td>${x}</td>`).join("")}</tr>`).join("")}</tbody>`;
  host.innerHTML = `<div class="tv-wrap"><table class="tv">${caption ? `<caption>${caption}</caption>` : ""}${h}${b}</table></div>`;
}

/** 横棒の対比(2 系列)。値は必ず数字も添える */
export function pairBars(host, rows, opts = {}) {
  const { labelA = "地の文", labelB = "会話文", digits = 3, max = null } = opts;
  const top = max ?? Math.max(...rows.flatMap((r) => [r.a, r.b]), 1e-9);
  host.innerHTML = rows
    .map((r) => {
      const wa = (r.a / top) * 100, wb = (r.b / top) * 100;
      return `<div class="pair">
        <div class="pk">${r.k}</div>
        <div class="pb"><i style="width:${wa}%;background:var(--jinomon-strong)"></i>
          <span>${fmt(r.a, digits)}</span></div>
        <div class="pb"><i style="width:${wb}%;background:var(--series-1)"></i>
          <span>${fmt(r.b, digits)}</span></div>
      </div>`;
    })
    .join("") +
    `<div class="pair head"><div class="pk"></div><div class="pk">${labelA}</div><div class="pk">${labelB}</div></div>`;
}
