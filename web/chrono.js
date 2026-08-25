/* 連載回クロノグラフ(F-18)
 *
 * 章をそのまま単位にすると孤立度が語数の関数になる(HC-025)。等サイズブロックを
 * 単位に取り直し、章ラベルの置換検定を対照に置いた結果を出す。
 */
import { axisX, axisY, css, el, fmt, niceTicks, readout, svg, table } from "./chart.js";

let D = null;
let voice = "jinomon";
let focusCh = null;
const say = readout("readout");

const chLabel = (i) => `第${["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一"][+i]}章`;

/* ---- 初出年月の帯 -------------------------------------------------------- */

function drawSerial() {
  const s = D.serial;
  const host = document.getElementById("serial");
  const cells = s.issues
    .map((i) => `<span class="issue"><b>${i.year}</b>年${i.month}月</span>`)
    .join("");
  host.innerHTML = `<div class="issues">${cells}</div>
    <p class="note">『${s.issues[0].media}』に <strong>${s.count} 回</strong>。
      章は <strong>${s.chapter_count}</strong> あるので <strong>1 対 1 ではない</strong>。
      どの回が 2 章分を含むかを決められる出所を持たないので、
      <strong>章と回の対応表は作っていません</strong>(${s.status.split("—")[0].trim()})。
      下の文体分析はすべて<strong>章</strong>を単位にしています。</p>`;
}

/* ---- 素朴版の交絡 -------------------------------------------------------- */

function drawNaive() {
  const rows = ["jinomon", "kaiwa", "all"].map((v) => {
    const b = D.naive[v];
    const min = Math.min(...b.tokens), max = Math.max(...b.tokens);
    return [
      { jinomon: "地の文", kaiwa: "会話文", all: "全文" }[v],
      fmt(min), fmt(max), `${fmt(max / min, 1)} 倍`,
      `<b>${b.size_confound_r > 0 ? "+" : ""}${fmt(b.size_confound_r, 3)}</b>`,
      b.usable ? "使える" : "<b>解釈に使わない</b>",
    ];
  });
  table(
    document.getElementById("naive"),
    ["単位", "最小語数", "最大語数", "大きさの比", "孤立度と log 語数の相関", "判定"],
    rows
  );
}

/* ---- ブロック PCA 散布図 ------------------------------------------------- */

function drawScatter() {
  const b = D.blocks[voice];
  const host = document.getElementById("scatter");
  host.innerHTML = "";
  if (!b || !b.coords) { host.textContent = "ブロックが足りません。"; return; }

  const W = 720, H = 420, m = { l: 46, r: 16, t: 14, b: 34 };
  const xs = b.coords.map((c) => c[0]), ys = b.coords.map((c) => c[1]);
  const xr = [Math.min(...xs), Math.max(...xs)], yr = [Math.min(...ys), Math.max(...ys)];
  const pad = (r) => [r[0] - (r[1] - r[0]) * 0.08, r[1] + (r[1] - r[0]) * 0.08];
  const [x0, x1] = pad(xr), [y0, y1] = pad(yr);
  const sx = (v) => m.l + ((v - x0) / (x1 - x0)) * (W - m.l - m.r);
  const sy = (v) => H - m.b - ((v - y0) / (y1 - y0)) * (H - m.t - m.b);

  const s = svg(W, H);
  const g = el("g");
  axisY(g, m.l, m.t, H - m.b,
    niceTicks(y0, y1, 5).map((v) => ({ v, y: sy(v), w: W - m.l - m.r })), (v) => fmt(v, 1));
  axisX(g, m.l, W - m.r, H - m.b,
    niceTicks(x0, x1, 6).map((v) => ({ v, x: sx(v) })), (v) => fmt(v, 1));

  b.coords.forEach((c, i) => {
    const ch = b.labels[i];
    const on = focusCh === null || focusCh === ch;
    const t = el("text", {
      x: sx(c[0]), y: sy(c[1]) + 4, "text-anchor": "middle", "font-size": on ? 12 : 11,
      "font-weight": focusCh === ch ? 700 : 400,
      fill: focusCh === ch ? css("--series-1") : (on ? css("--ink-2") : css("--ink-muted")),
      opacity: on ? 1 : 0.35, tabindex: 0, role: "img",
      "aria-label": `${chLabel(ch)}のブロック`,
    });
    t.textContent = ch;
    const msg = `${chLabel(ch)} のブロック / PC1 ${fmt(c[0], 2)} PC2 ${fmt(c[1], 2)}`
      + (voice === "all" ? ` / このブロックの会話率 ${fmt(b.kaiwa_share[i] * 100, 0)}%` : "");
    t.addEventListener("mouseenter", () => say(msg));
    t.addEventListener("focus", () => say(msg));
    g.append(t);
  });
  s.append(g);
  host.append(s);

  document.getElementById("scatterNote").innerHTML =
    `点は <strong>${b.blocks} 個の等サイズブロック</strong>(各 ${fmt(b.block_size)} 語)。
     数字はそのブロックが属する章です — <strong>章を色で符号化していません</strong>
     (11 章を順序ランプに載せると隣接段の明度差が足りず、検証に落ちるため)。
     PC1 ${fmt(b.explained[0] * 100, 1)}% / PC2 ${fmt(b.explained[1] * 100, 1)}% を説明。`
    + (voice === "all"
      ? ` <strong>この全文版では PC1 と会話率の相関が r = ${fmt(b.pc1_vs_kaiwa_share_r, 3)}</strong> —
          二声を分けないと第一主成分が「文体」ではなく「会話率」を測ります。`
      : "");
}

/* ---- 章別の孤立度と p 値 ------------------------------------------------- */

function drawIsolation() {
  const b = D.blocks[voice];
  const host = document.getElementById("isolation");
  host.innerHTML = "";
  if (!b || !b.per_chapter) return;

  const chs = b.chapters;
  const W = 720, H = 40 + chs.length * 26, m = { l: 64, r: 120, t: 16, b: 26 };
  const vals = chs.flatMap((c) => [b.per_chapter[c].between, b.per_chapter[c].null_mean]);
  const [x0, x1] = [Math.min(...vals) * 0.995, Math.max(...vals) * 1.005];
  const sx = (v) => m.l + ((v - x0) / (x1 - x0)) * (W - m.l - m.r);

  const s = svg(W, H);
  const g = el("g");
  axisX(g, m.l, W - m.r, H - m.b,
    niceTicks(x0, x1, 5).map((v) => ({ v, x: sx(v) })), (v) => fmt(v, 2));

  chs.forEach((c, i) => {
    const e = b.per_chapter[c];
    const y = m.t + i * 26;
    const sig = e.p < 0.05;
    const lab = el("text", { x: m.l - 8, y: y + 4, "text-anchor": "end", "font-size": 11,
      fill: sig ? css("--ink") : css("--ink-2"), "font-weight": sig ? 700 : 400 });
    lab.textContent = chLabel(c);
    g.append(lab);
    // 帰無平均 → 観測値 の線と点
    g.append(el("line", { x1: sx(e.null_mean), x2: sx(e.between), y1: y, y2: y,
      stroke: css("--rule"), "stroke-width": 2 }));
    g.append(el("circle", { cx: sx(e.null_mean), cy: y, r: 3, fill: css("--ink-muted") }));
    const dot = el("circle", { cx: sx(e.between), cy: y, r: 5,
      fill: sig ? css("--series-1") : css("--axis"),
      stroke: css("--surface"), "stroke-width": 2, tabindex: 0, role: "img",
      "aria-label": `${chLabel(c)} 章間距離 ${fmt(e.between, 3)} p=${fmt(e.p, 3)}` });
    const msg = `${chLabel(c)} ブロック ${e.blocks} 個／章間 ${fmt(e.between, 3)}`
      + `・帰無平均 ${fmt(e.null_mean, 3)}・p = ${fmt(e.p, 3)}`
      + (e.within === null ? "・章内は 1 ブロックしかないため測れない" : `・章内 ${fmt(e.within, 3)}`);
    dot.addEventListener("mouseenter", () => say(msg));
    dot.addEventListener("focus", () => say(msg));
    g.append(dot);
    const pv = el("text", { x: W - m.r + 8, y: y + 4, "font-size": 11,
      fill: sig ? css("--series-1") : css("--ink-muted") });
    pv.textContent = `p = ${fmt(e.p, 3)}${sig ? " ✓" : ""}`;
    g.append(pv);
  });
  s.append(g);
  host.append(s);

  const sig = chs.filter((c) => b.per_chapter[c].p < 0.05);
  document.getElementById("isolationNote").innerHTML =
    `丸が観測値、小さい点が置換検定の帰無平均。<strong>章ラベル全体の検定は
     観測 ${fmt(b.observed, 4)} 対 帰無 ${fmt(b.null_mean, 4)}±${fmt(b.null_sd, 4)}、
     p = ${fmt(b.p_value, 4)}</strong>(${fmt(b.permutations)} 回・seed ${b.seed})。
     つまり<strong>同じ章のブロックは互いに似ている</strong> — 章という単位に文体の信号があります。
     個別に有意(p &lt; 0.05)なのは ${sig.length ? sig.map(chLabel).join("・") : "なし"}。
     サイズ交絡は r = ${fmt(b.size_confound_r, 3)} まで下がっています
     (素朴版は ${fmt(D.naive[voice] ? D.naive[voice].size_confound_r : 0, 3)})。`;

  table(
    document.getElementById("isoTable"),
    ["章", "ブロック", "章内", "章間", "帰無平均", "p"],
    chs.map((c) => {
      const e = b.per_chapter[c];
      return [chLabel(c), e.blocks, e.within === null ? "—" : fmt(e.within, 3),
        fmt(e.between, 3), fmt(e.null_mean, 3),
        e.p < 0.05 ? `<b>${fmt(e.p, 3)}</b>` : fmt(e.p, 3)];
    })
  );
}

/* ---- rolling delta ------------------------------------------------------- */

function drawRolling() {
  const r = D.rolling;
  const host = document.getElementById("rolling");
  host.innerHTML = "";
  const W = 900, H = 260, m = { l: 46, r: 16, t: 14, b: 34 };
  const pts = r.series.filter((p) => p.from_prev !== null);
  const ys = pts.map((p) => p.from_prev);
  const [y0, y1] = [Math.min(...ys) * 0.98, Math.max(...ys) * 1.02];
  const sx = (t) => m.l + (t / r.tokens) * (W - m.l - m.r);
  const sy = (v) => H - m.b - ((v - y0) / (y1 - y0)) * (H - m.t - m.b);

  const s = svg(W, H);
  const g = el("g");
  axisY(g, m.l, m.t, H - m.b,
    niceTicks(y0, y1, 4).map((v) => ({ v, y: sy(v), w: W - m.l - m.r })), (v) => fmt(v, 2));
  axisX(g, m.l, W - m.r, H - m.b,
    niceTicks(0, r.tokens, 6).map((v) => ({ v, x: sx(v) })), (v) => fmt(v / 1000, 0) + "k");

  for (const b of r.chapter_bounds) {
    if (b.token === 0) continue;
    g.append(el("line", { x1: sx(b.token), x2: sx(b.token), y1: m.t, y2: H - m.b,
      stroke: css("--axis"), "stroke-dasharray": null, "stroke-width": 1, opacity: 0.7 }));
    const t = el("text", { x: sx(b.token) + 3, y: m.t + 10, "font-size": 9, fill: css("--ink-muted") });
    t.textContent = b.label;
    g.append(t);
  }

  const d = pts.map((p, i) => `${i ? "L" : "M"}${sx(p.start)},${sy(p.from_prev)}`).join(" ");
  g.append(el("path", { d, fill: "none", stroke: css("--series-1"), "stroke-width": 2,
    "stroke-linejoin": "round" }));

  // 最大の切り替わり点だけを直接ラベルする
  const peak = pts.reduce((a, b2) => (b2.from_prev > a.from_prev ? b2 : a));
  g.append(el("circle", { cx: sx(peak.start), cy: sy(peak.from_prev), r: 4,
    fill: css("--series-2"), stroke: css("--surface"), "stroke-width": 2 }));
  const pl = el("text", { x: sx(peak.start) + 7, y: sy(peak.from_prev) - 6, "font-size": 10,
    fill: css("--series-2") });
  pl.textContent = `最大 ${fmt(peak.from_prev, 2)}`;
  g.append(pl);

  const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b,
    fill: "transparent", tabindex: 0 });
  hit.addEventListener("mousemove", (e) => {
    const box = s.getBoundingClientRect();
    const tok = ((e.clientX - box.left) / box.width * W - m.l) / (W - m.l - m.r) * r.tokens;
    const p = pts.reduce((a, b2) => (Math.abs(b2.start - tok) < Math.abs(a.start - tok) ? b2 : a));
    const ch = r.chapter_bounds.filter((b2) => b2.token <= p.start).pop();
    say(`地の文 ${fmt(p.start)} 語目(${ch ? ch.label : "?"})／直前の窓との距離 ${fmt(p.from_prev, 3)}`
      + `・第一章の重心からの距離 ${fmt(p.from_ch1, 3)}`);
  });
  hit.addEventListener("focus", () => say(`窓 ${fmt(D.window)} 語・刻み ${fmt(D.step)} 語で ${pts.length} 点`));
  g.append(hit);
  s.append(g);
  host.append(s);

  document.getElementById("rollingNote").innerHTML =
    `地の文だけを ${fmt(D.window)} 語の窓・${fmt(D.step)} 語刻みで滑らせ、
     <strong>直前の窓との文体距離</strong>を描いています。窓は等サイズなのでサイズ交絡はありません。
     縦線は章境界。<strong>山が章境界と一致すれば「章の切り替わりが文体の切り替わり」</strong>、
     一致しなければ章の内側に切れ目があることになります。`;
}

/* ---- 組み立て ------------------------------------------------------------ */

function renderAll() {
  drawScatter();
  drawIsolation();
}

async function main() {
  D = await (await fetch("data/chrono.json")).json();
  drawSerial();
  drawNaive();
  drawRolling();

  const sel = document.getElementById("voice");
  sel.innerHTML = [["jinomon", "地の文"], ["kaiwa", "会話文"], ["all", "全文(対照)"]]
    .filter(([k]) => D.blocks[k])
    .map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
  sel.addEventListener("change", () => { voice = sel.value; renderAll(); });

  const chSel = document.getElementById("focusCh");
  chSel.innerHTML = `<option value="">強調しない</option>` +
    D.blocks.jinomon.chapters.map((c) => `<option value="${c}">${chLabel(c)}</option>`).join("");
  chSel.addEventListener("change", () => { focusCh = chSel.value || null; drawScatter(); });

  renderAll();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    renderAll(); drawRolling();
  });
}

main();
