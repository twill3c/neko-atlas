/* 配置(F-20)— 語彙分散プロット。
 *
 * 筋を持たない作品なので感情価曲線は効かない。「どの語がどこに固まって出るか」が
 * そのまま構成図になる。**主題語は手で選ばず、章別分布の偏り(Juilland の D)で選ぶ。**
 */
import { css, el, fmt, readout, svg, table } from "./chart.js";

let H = null;
let mode = "concentrated";
const say = readout("readout");
/** UniDic の語彙素は同形異義に "-助数詞" のような接尾が付く。表示のときだけ落とす
 *  (キーは落とさない — 別語を混ぜないため)。形態素の切れ端(例「衛門」)はそのまま出す。 */
const disp = (lemma) => lemma.replace(/-[^-]+$/, "");

const chLabel = (i) => `第${["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一"][+i]}章`;

function terms() {
  if (mode === "persons") {
    const seen = new Map();
    for (const [alias, display] of Object.entries(H.person_terms)) {
      if (!H.occurrences[alias]) continue;
      // 同一人物の異名はまとめて 1 行にする
      const cur = seen.get(display) || { label: display, aliases: [], hits: [] };
      cur.aliases.push(alias);
      cur.hits = cur.hits.concat(H.occurrences[alias]);
      seen.set(display, cur);
    }
    return [...seen.values()]
      .map((t) => ({ ...t, hits: t.hits.sort((a, b) => a - b) }))
      .sort((a, b) => b.hits.length - a.hits.length);
  }
  return H.concentrated
    .filter((c) => H.occurrences[c.lemma])
    .map((c) => ({ label: disp(c.lemma), aliases: [c.lemma], hits: H.occurrences[c.lemma],
      d: c.d, peak: c.peak_chapter }));
}

function draw() {
  const rows = terms();
  const host = document.getElementById("dispersion");
  host.innerHTML = "";
  const W = 980, rowH = 22, m = { l: 168, r: 56, t: 30, b: 26 };
  const Hgt = m.t + rows.length * rowH + m.b;
  const sx = (off) => m.l + (off / H.body_chars) * (W - m.l - m.r);

  const s = svg(W, Hgt);
  const g = el("g");

  // 章の帯(交互に薄く敷く)と章ラベル
  H.chapters.forEach((c, i) => {
    if (i % 2 === 0) {
      g.append(el("rect", { x: sx(c.start), y: m.t - 6, width: sx(c.end) - sx(c.start),
        height: rows.length * rowH + 6, fill: css("--rule"), opacity: 0.5 }));
    }
    const t = el("text", { x: (sx(c.start) + sx(c.end)) / 2, y: m.t - 12,
      "text-anchor": "middle", "font-size": 9, fill: css("--ink-muted") });
    t.textContent = c.label;
    g.append(t);
  });

  rows.forEach((r, i) => {
    const y = m.t + i * rowH;
    const lab = el("text", { x: m.l - 10, y: y + rowH / 2 + 3, "text-anchor": "end",
      "font-size": 11, fill: css("--ink-2") });
    lab.textContent = r.label;
    g.append(lab);
    const n = el("text", { x: W - m.r + 8, y: y + rowH / 2 + 3, "font-size": 10,
      fill: css("--ink-muted") });
    n.textContent = r.d !== undefined ? `D ${fmt(r.d, 2)}` : fmt(r.hits.length);
    g.append(n);

    for (const off of r.hits) {
      g.append(el("line", { x1: sx(off), x2: sx(off), y1: y + 4, y2: y + rowH - 4,
        stroke: css("--series-1"), "stroke-width": 1.2, opacity: 0.8 }));
    }
    const hit = el("rect", { x: m.l, y, width: W - m.l - m.r, height: rowH,
      fill: "transparent", tabindex: 0, role: "img",
      "aria-label": `${r.label} ${r.hits.length} 回` });
    const peak = r.peak !== undefined ? `・最も濃いのは${chLabel(r.peak)}` : "";
    const msg = `${r.label}（${r.aliases.join("・")}）${fmt(r.hits.length)} 回`
      + (r.d !== undefined ? `・偏り D = ${fmt(r.d, 3)}${peak}` : "");
    hit.addEventListener("mouseenter", () => say(msg));
    hit.addEventListener("focus", () => say(msg));
    hit.addEventListener("click", () => {
      if (r.hits.length) location.href = `reader.html?ch=${chapterOf(r.hits[0])}&pos=${r.hits[0]}`;
    });
    g.append(hit);
  });
  s.append(g);
  host.append(s);
}

function chapterOf(off) {
  const c = H.chapters.find((x) => x.start <= off && off < x.end);
  return c ? c.index : 1;
}

function drawTable() {
  table(
    document.getElementById("dtable"),
    ["語", "総出現", "偏り D", "最も濃い章", "その章が占める割合"],
    H.concentrated.map((c) => [
      disp(c.lemma), fmt(c.total), fmt(c.d, 3), chLabel(c.peak_chapter),
      `${fmt(c.peak_share * 100, 0)}%`,
    ]),
    `D は Juilland の分散度。1 に近いほど全章に均等、0 に近いほど一箇所に固まる。`
    + `総出現 ${H.min_freq} 回以上の名詞・動詞・形容詞から採った。`
    + `「衛門」のように形態素の切れ端が混じることがある — 隠さずそのまま出している。`
  );
}

async function main() {
  H = await (await fetch("data/haichi.json")).json();
  document.getElementById("note").textContent = H.note;
  const sel = document.getElementById("mode");
  sel.addEventListener("change", () => { mode = sel.value; draw(); });
  draw();
  drawTable();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
}

main();
