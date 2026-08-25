/* 二声(F-19)— 地の文と会話文を別コーパスとして対比する。
 * 併せて「分けないと何を測ることになるか」を数値で実演する(T-503)。
 */
import { axisX, axisY, css, el, fmt, niceTicks, pairBars, readout, svg, table } from "./chart.js";

let F = null, C = null, dict = "gendai";
const say = readout("readout");
const chLabel = (i) => `第${["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一"][+i]}章`;

function d() { return F.dicts[dict]; }

function drawGoshu() {
  const v = d().by_voice;
  const keys = ["和", "漢", "外", "混", "固", "記号"];
  pairBars(
    document.getElementById("goshu"),
    keys.map((k) => ({ k: `${k}語`, a: v.jinomon.goshu_ratio[k] || 0, b: v.kaiwa.goshu_ratio[k] || 0 })),
    { digits: 3 }
  );
}

function drawPos() {
  const v = d().by_voice;
  const keys = [...new Set([...Object.keys(v.jinomon.pos1_ratio), ...Object.keys(v.kaiwa.pos1_ratio)])]
    .sort((a, b) => (v.jinomon.pos1_ratio[b] || 0) - (v.jinomon.pos1_ratio[a] || 0))
    .slice(0, 9);
  pairBars(
    document.getElementById("pos"),
    keys.map((k) => ({ k, a: v.jinomon.pos1_ratio[k] || 0, b: v.kaiwa.pos1_ratio[k] || 0 })),
    { digits: 3 }
  );
}

/** 文長の分布。2 本を重ねると読めないので、上下に並べた 2 段のヒストグラムにする */
function drawLen() {
  const v = d().by_voice;
  const host = document.getElementById("lenhist");
  host.innerHTML = "";
  const bins = [...new Set([...Object.keys(v.jinomon.sentence_len.histogram),
    ...Object.keys(v.kaiwa.sentence_len.histogram)])].map(Number).sort((a, b) => a - b);
  const W = 720, rowH = 110, gap = 26, m = { l: 46, r: 16, t: 12, b: 30 };
  const H = rowH * 2 + gap + m.t + m.b;
  const maxShare = Math.max(...["jinomon", "kaiwa"].flatMap((k) => {
    const h = v[k].sentence_len.histogram, tot = Object.values(h).reduce((a, b) => a + b, 0);
    return Object.values(h).map((x) => x / tot);
  }));
  const bw = (W - m.l - m.r) / bins.length;
  const s = svg(W, H);
  const g = el("g");
  ["jinomon", "kaiwa"].forEach((k, r) => {
    const h = v[k].sentence_len.histogram;
    const tot = Object.values(h).reduce((a, b) => a + b, 0);
    const y0 = m.t + r * (rowH + gap);
    const base = y0 + rowH;
    axisY(g, m.l, y0, base,
      niceTicks(0, maxShare, 3).map((val) => ({ v: val, y: base - (val / maxShare) * rowH, w: W - m.l - m.r })),
      (val) => fmt(val * 100, 0) + "%");
    const lab = el("text", { x: m.l, y: y0 - 2, "font-size": 11,
      fill: k === "jinomon" ? css("--ink-2") : css("--series-1") });
    lab.textContent = `${k === "jinomon" ? "地の文" : "会話文"}(平均 ${fmt(v[k].sentence_len.mean, 1)} 字・中央 ${v[k].sentence_len.median}・p90 ${v[k].sentence_len.p90})`;
    g.append(lab);
    bins.forEach((b, i) => {
      const share = (h[b] || 0) / tot;
      const bh = (share / maxShare) * rowH;
      const rect = el("rect", { x: m.l + i * bw + 1, y: base - bh, width: Math.max(1, bw - 2),
        height: bh, rx: 2, fill: k === "jinomon" ? css("--jinomon-strong") : css("--series-1"),
        tabindex: 0, role: "img",
        "aria-label": `${k === "jinomon" ? "地の文" : "会話文"} ${b}〜${b + 9}字 ${fmt(share * 100, 1)}%` });
      const msg = `${k === "jinomon" ? "地の文" : "会話文"}／文長 ${b}〜${b + 9} 字：`
        + `${fmt(h[b] || 0)} 文(${fmt(share * 100, 1)}%)`;
      rect.addEventListener("mouseenter", () => say(msg));
      rect.addEventListener("focus", () => say(msg));
      g.append(rect);
    });
    if (r === 1) {
      axisX(g, m.l, W - m.r, base,
        bins.filter((_, i) => i % 4 === 0).map((b, i) => ({ v: b, x: m.l + i * 4 * bw + bw / 2 })),
        (val) => (val >= 200 ? "200+" : String(val)));
    }
  });
  s.append(g);
  host.append(s);
}

function drawBunmatsu() {
  const v = d().by_voice;
  const rows = [];
  const n = Math.max(v.jinomon.bunmatsu_top.length, v.kaiwa.bunmatsu_top.length);
  for (let i = 0; i < Math.min(10, n); i++) {
    const a = v.jinomon.bunmatsu_top[i], b = v.kaiwa.bunmatsu_top[i];
    rows.push([i + 1, a ? `${a.form}（${fmt(a.n)}）` : "—", b ? `${b.form}（${fmt(b.n)}）` : "—"]);
  }
  table(document.getElementById("bunmatsu"), ["#", "地の文", "会話文"], rows);
}

function drawBigram() {
  const v = d().by_voice;
  const rows = [];
  for (let i = 0; i < 10; i++) {
    const a = v.jinomon.pos_bigram_top[i], b = v.kaiwa.pos_bigram_top[i];
    rows.push([i + 1, a ? `${a.pair}（${fmt(a.n)}）` : "—", b ? `${b.pair}（${fmt(b.n)}）` : "—"]);
  }
  table(document.getElementById("bigram"), ["#", "地の文", "会話文"], rows);
}

function drawDemo() {
  const all = C.blocks.all, jino = C.blocks.jinomon;
  document.getElementById("demo").innerHTML = `
    <p class="note">同じ手順(等サイズブロック → MFW ${C.mfw} 語 → z 化 → 主成分)を、
      <strong>二声を分けた場合</strong>と<strong>混ぜた場合</strong>に当てて比べます。</p>
    <div class="tv-wrap"><table class="tv">
      <thead><tr><th>単位</th><th>ブロック</th><th>PC1 の説明率</th>
        <th>PC1 と会話率の相関</th><th>読み</th></tr></thead>
      <tbody>
        <tr><td>地の文だけ</td><td>${fmt(jino.blocks)}</td>
          <td>${fmt(jino.explained[0] * 100, 1)}%</td><td>—（会話率が定義できない）</td>
          <td>文体を測っている</td></tr>
        <tr><td><b>全文（混ぜる）</b></td><td>${fmt(all.blocks)}</td>
          <td>${fmt(all.explained[0] * 100, 1)}%</td>
          <td><b>r = ${fmt(all.pc1_vs_kaiwa_share_r, 3)}</b></td>
          <td><b>会話率を測っている</b></td></tr>
      </tbody>
    </table></div>
    <p class="note">全文で測ると第一主成分が<strong>ブロックの会話率とほぼ一直線に相関</strong>します。
      章によって会話率が 11%〜78% と振れるこの作品では、二声を分けないかぎり
      「文体の違い」ではなく「会話がどれだけ入っているか」を測ることになります。
      文体分析が地の文だけを使う理由が、そのまま数値になっています。</p>`;
}

function drawByChapter() {
  const rows = d().by_chapter.map((e) => [
    chLabel(e.chapter),
    fmt(e.jinomon.chars), fmt(e.jinomon.sentence_len_mean, 1), fmt(e.jinomon.goshu_ratio["漢"] || 0, 3),
    fmt(e.kaiwa.chars), fmt(e.kaiwa.sentence_len_mean, 1), fmt(e.kaiwa.goshu_ratio["漢"] || 0, 3),
  ]);
  table(document.getElementById("bych"),
    ["章", "地の文 字数", "地 文長平均", "地 漢語率", "会話 字数", "会 文長平均", "会 漢語率"], rows);
}

function renderAll() {
  document.getElementById("dictNote").textContent =
    `${d().label}／ライセンス ${d().license}`;
  drawGoshu(); drawPos(); drawLen(); drawBunmatsu(); drawBigram(); drawByChapter();
}

async function main() {
  [F, C] = await Promise.all([
    (await fetch("data/futakoe.json")).json(),
    (await fetch("data/chrono.json")).json(),
  ]);
  const sel = document.getElementById("dict");
  sel.innerHTML = Object.entries(F.dicts)
    .map(([k, v]) => `<option value="${k}">${v.label}</option>`).join("");
  sel.addEventListener("change", () => { dict = sel.value; renderAll(); });
  renderAll();
  drawDemo();
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderAll);
}

main();
