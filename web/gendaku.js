/* 衒学カタログ(F-22)
 *
 * 分類は統制語彙による手作業。**各語に本文中の文脈を出所として付ける** —
 * 分類の判断は人手だが、読者が本文で確かめられるようにする。
 * 統制語彙に入れなかった候補は件数を出して限界を隠さない。
 */
import { axisX, axisY, css, el, fmt, niceTicks, readout, svg, table } from "./chart.js";

let G = null;
let filterClass = "";
const say = readout("readout");
const chLabel = (i) => `第${["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一"][+i]}章`;
const COLOR = { "西洋": "--series-1", "漢籍": "--series-2", "同時代日本": "--series-3" };

function found() { return G.entries.filter((e) => !e.needs_review); }

/** 章別の出現密度(千字あたり)。分類は 3 つなので色で符号化してよい(検証済み) */
function drawByChapter() {
  const host = document.getElementById("bychapter");
  host.innerHTML = "";
  const chs = G.chapters;
  const per = {};
  for (const cls of G.classes) {
    per[cls] = chs.map((c) => {
      const n = found()
        .filter((e) => e.class === cls)
        .reduce((a, e) => a + (e.by_chapter[String(c.index)] || 0), 0);
      return (n / c.chars) * 1000;
    });
  }
  const W = 860, H = 300, m = { l: 52, r: 16, t: 16, b: 40 };
  const maxV = Math.max(...G.classes.flatMap((c) => per[c]));
  const bw = (W - m.l - m.r) / chs.length;
  const gw = (bw - 10) / 3;

  const s = svg(W, H);
  const g = el("g");
  axisY(g, m.l, m.t, H - m.b,
    niceTicks(0, maxV, 5).map((v) => ({ v, y: H - m.b - (v / maxV) * (H - m.t - m.b),
      w: W - m.l - m.r })), (v) => fmt(v, 1));
  axisX(g, m.l, W - m.r, H - m.b,
    chs.map((c, i) => ({ v: c.label, x: m.l + i * bw + bw / 2 })), (v) => v);

  chs.forEach((c, i) => {
    G.classes.forEach((cls, k) => {
      const v = per[cls][i];
      const h = (v / maxV) * (H - m.t - m.b);
      const x = m.l + i * bw + 5 + k * gw;
      const rect = el("rect", { x, y: H - m.b - h, width: Math.max(1, gw - 2), height: h,
        rx: 2, fill: css(COLOR[cls]), tabindex: 0, role: "img",
        "aria-label": `${chLabel(c.index)} ${cls} ${fmt(v, 2)}/千字` });
      const n = found().filter((e) => e.class === cls)
        .reduce((a, e) => a + (e.by_chapter[String(c.index)] || 0), 0);
      const msg = `${chLabel(c.index)}／${cls}：${fmt(n)} 回・${fmt(v, 2)} 回/千字`;
      rect.addEventListener("mouseenter", () => say(msg));
      rect.addEventListener("focus", () => say(msg));
      g.append(rect);
    });
  });
  s.append(g);
  host.append(s);

  document.getElementById("legend").innerHTML = G.classes
    .map((c) => `<span class="item"><i class="sw" style="background:var(${COLOR[c]})"></i>${c}</span>`)
    .join("");
}

function drawCatalog() {
  const rows = found()
    .filter((e) => !filterClass || e.class === filterClass)
    .map((e) => [
      `<b>${e.surface}</b>`, e.class, e.kind, fmt(e.total),
      chLabel(peakOf(e)),
      `<span class="ev">…${e.evidence.replace(/[<>&]/g, "")}…</span>`,
      e.note || "—",
    ]);
  table(document.getElementById("catalog"),
    ["表記", "分類", "種別", "出現", "最も濃い章", "本文の文脈(出所)", "注"], rows,
    `統制語彙 ${fmt(G.entries.length)} 語。<strong>すべて本文と照合済み</strong>で、`
    + `各語に本文中の文脈を出所として添えてあります。`);
}

function peakOf(e) {
  return Object.entries(e.by_chapter).reduce((a, b) => (b[1] > a[1] ? b : a), ["1", -1])[0];
}

function drawLimits() {
  const u = G.unclassified;
  document.getElementById("limits").innerHTML = `
    <p class="note">統制語彙に入れなかった候補が <strong>${fmt(u.candidates)} 種・延べ
      ${fmt(u.occurrences)}</strong> あります(${u.min_freq} 回以上・作中人物を除く)。${u.note}。
      分類の根拠を持てないものを推定で埋めていないので、このカタログは<strong>網羅ではありません</strong>。</p>
    <div class="issues">${u.top.slice(0, 30)
      .map((x) => `<span class="issue">${x.surface}<b> ${x.n}</b></span>`).join("")}</div>`;
}

function drawSummary() {
  const f = found();
  const tiles = G.classes.map((c) => {
    const es = f.filter((e) => e.class === c);
    return [`${fmt(es.reduce((a, e) => a + e.total, 0))}`,
      `${c}（${fmt(es.length)} 語）`];
  });
  document.getElementById("tiles").innerHTML = tiles
    .map(([v, k]) => `<div class="tile"><div class="v">${v}</div><div class="k">${k}</div></div>`)
    .join("");
}

async function main() {
  G = await (await fetch("data/gendaku.json")).json();
  const sel = document.getElementById("cls");
  sel.innerHTML = `<option value="">すべての分類</option>`
    + G.classes.map((c) => `<option value="${c}">${c}</option>`).join("");
  sel.addEventListener("change", () => { filterClass = sel.value; drawCatalog(); });
  drawSummary();
  drawByChapter();
  drawCatalog();
  drawLimits();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawByChapter);
}

main();
