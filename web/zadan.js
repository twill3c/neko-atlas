/* 座談(F-21・縮退版)
 *
 * **応酬ネットワークは出荷しない。** 帰属率 16.5% では隣接 2 発話がともに帰属している
 * 確率が約 2.7% にとどまり辺が引けず、交替既定も構造的に発火しない(SPEC §4 の縮退条件)。
 * ここに出すのは章 × 人物の発話量と、章ごとの帰属率。**「不明」は第一級の項目**として扱う。
 */
import { axisX, axisY, css, el, fmt, niceTicks, readout, svg, table } from "./chart.js";

let Z = null;
let metric = "utterances";
const say = readout("readout");
const chLabel = (i) => `第${["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一"][+i]}章`;

function topSpeakers(n = 3) {
  return Z.totals.slice(0, n).map((t) => t.id);
}

function drawDegraded() {
  const d = Z.degraded;
  document.getElementById("degraded").innerHTML = `
    <p class="note"><strong>応酬ネットワークは出荷していません。</strong>${d.reason}。
      帰属率 ${fmt(d.attribution_rate * 100, 1)}% では、隣接する 2 発話がともに帰属している確率は
      <strong>約 ${fmt(d.adjacent_pair_probability * 100, 1)}%</strong> にとどまり、辺がほとんど引けません。
      さらに、地の文を挟まない連続発話の塊のうち<strong>既知の帰属が 2 件以上ある塊は
      ${d.runs_with_two_or_more_known} 個</strong>なので、交替の位相も決められません
      (交替既定による補完は実測 ${d.r4_filled} 件)。
      推定で辺を引けば図はできますが、それは本文が言っていないことを描くことになります。</p>`;
}

function drawStack() {
  const host = document.getElementById("stack");
  host.innerHTML = "";
  const top = topSpeakers(3);
  const W = 860, m = { l: 66, r: 190, t: 14, b: 32 };
  const rowH = 30, H = m.t + Z.by_chapter.length * rowH + m.b;

  const value = (e, id) => (metric === "utterances" ? (e.speakers[id] || 0) : (e.chars[id] || 0));
  const totalOf = (e) => (metric === "utterances"
    ? e.utterances
    : Object.values(e.chars).reduce((a, b) => a + b, 0) + e.unknownChars);
  // 不明の分量は「発話数」でのみ厳密に出せる。字数では帰属済みしか持っていない
  for (const e of Z.by_chapter) e.unknownChars = 0;

  const maxTotal = Math.max(...Z.by_chapter.map((e) =>
    metric === "utterances" ? e.utterances
      : Object.values(e.chars).reduce((a, b) => a + b, 0)));
  const sx = (v) => m.l + (v / maxTotal) * (W - m.l - m.r);

  const s = svg(W, H);
  const g = el("g");
  axisX(g, m.l, W - m.r, H - m.b,
    niceTicks(0, maxTotal, 5).map((v) => ({ v, x: sx(v) })), (v) => fmt(v));

  Z.by_chapter.forEach((e, i) => {
    const y = m.t + i * rowH;
    const lab = el("text", { x: m.l - 8, y: y + 16, "text-anchor": "end", "font-size": 11,
      fill: css("--ink-2") });
    lab.textContent = chLabel(e.chapter);
    g.append(lab);

    const parts = [];
    top.forEach((id, k) => parts.push({ id, v: value(e, id), color: css(`--series-${k + 1}`),
      name: Z.persons[id] || id }));
    const other = Object.keys(e.speakers)
      .filter((id) => !top.includes(id))
      .reduce((a, id) => a + value(e, id), 0);
    parts.push({ id: "other", v: other, color: css("--series-other"), name: "その他の話者" });
    if (metric === "utterances") {
      parts.push({ id: "unknown", v: e.unknown, color: css("--unpainted"), name: "話者不明" });
    }

    let x = m.l;
    for (const p of parts) {
      if (p.v <= 0) continue;
      const w = sx(p.v) - m.l;
      const rect = el("rect", { x, y: y + 5, width: Math.max(1, w - 2), height: 16, rx: 2,
        fill: p.color, tabindex: 0, role: "img",
        "aria-label": `${chLabel(e.chapter)} ${p.name} ${fmt(p.v)}` });
      const msg = `${chLabel(e.chapter)}／${p.name}：${fmt(p.v)}`
        + (metric === "utterances" ? ` 発話（章の ${fmt(p.v / e.utterances * 100, 1)}%）` : " 字")
        + `／この章の帰属率 ${fmt(e.attribution_rate * 100, 0)}%`;
      rect.addEventListener("mouseenter", () => say(msg));
      rect.addEventListener("focus", () => say(msg));
      g.append(rect);
      x += w;
    }
    const rate = el("text", { x: W - m.r + 10, y: y + 17, "font-size": 11,
      fill: css("--ink-muted") });
    rate.textContent = metric === "utterances"
      ? `発話 ${fmt(e.utterances)}・帰属 ${fmt(e.attribution_rate * 100, 0)}%`
      : `帰属できた発話の字数のみ`;
    g.append(rate);
  });
  s.append(g);
  host.append(s);

  const legend = [
    ...top.map((id, k) => [`--series-${k + 1}`, Z.persons[id] || id]),
    ["--series-other", "その他の話者"],
    ...(metric === "utterances" ? [["--unpainted", "話者不明（塗らない）"]] : []),
  ];
  document.getElementById("legend").innerHTML = legend
    .map(([v, l]) => `<span class="item"><i class="sw" style="background:var(${v})"></i>${l}</span>`)
    .join("");
}

function drawTables() {
  table(document.getElementById("totals"),
    ["話者", "発話", "字数", "1 発話あたり"],
    Z.totals.map((t) => [t.display, fmt(t.utterances), fmt(t.chars),
      fmt(t.chars / t.utterances, 1)]),
    "帰属できた発話だけの集計です。全体の帰属率は "
    + `${fmt(Z.degraded.attribution_rate * 100, 1)}%、適合率は ${fmt(Z.precision, 3)}`
    + `（gold ${fmt(Z.gold_size)} 発話に対する実測）。`);

  table(document.getElementById("bych"),
    ["章", "発話", "帰属", "不明", "候補が複数", "帰属率 %"],
    Z.by_chapter.map((e) => [chLabel(e.chapter), fmt(e.utterances), fmt(e.attributed),
      fmt(e.unknown), fmt(e.ambiguous), fmt(e.attribution_rate * 100, 0)]));
}

async function main() {
  Z = await (await fetch("data/zadan.json")).json();
  document.getElementById("note").textContent = Z.note;
  document.getElementById("rules").innerHTML = Object.entries(Z.overall.by_rule)
    .map(([k, v]) => `<span class="issue"><b>${k}</b> ${fmt(v)}</span>`).join("");
  const sel = document.getElementById("metric");
  sel.addEventListener("change", () => { metric = sel.value; drawStack(); });
  drawDegraded();
  drawStack();
  drawTables();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawStack);
}

main();
