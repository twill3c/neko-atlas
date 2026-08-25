/* 応酬の帯(F-15 / F-15b / F-15c)
 *
 * 符号化の規律:
 *  - 俯瞰は集計値のみ。**交互濃淡を使わない**(発話の中央長が 0.6〜2.5 px でサブピクセル)
 *  - 詳細は 4 字/px。会話塊の中でのみ濃淡を交互に振る。交互は「前の発話と話者が違う」ことだけを主張する
 *  - 話者は帰属できたものだけを塗る。**不明は塗らない**
 */

const JINOMON = 0, KAIWA = 1, NOTATION = 2;
const CHARS_PER_PX = 4;      // 詳細の解像度(1 発話 ≒ 6px)
const DETAIL_ROW_H = 16;
const DETAIL_ROW_GAP = 4;
const RAMP_STOPS = [8, 20, 45, 110];   // 平均発話長のしきい(字)。分布 p25/p50/p75/p90 に由来

let BAND = null;
let overlay = "off";          // "off" | "all" | person id
let openChapter = null;

const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

function rampColor(meanLen) {
  let i = 0;
  while (i < RAMP_STOPS.length && meanLen > RAMP_STOPS[i]) i++;
  return css(`--kaiwa-${i}`);
}

/** 上位 3 話者に固定順でスロットを割り当てる。4 番目以降は「その他」に畳む
 *  (all-pairs で検証を通るのは 3 スロットまで — dataviz の検証結果)。 */
function speakerSlots() {
  const count = new Map();
  const { kind, speaker } = BAND.spans;
  for (let i = 0; i < kind.length; i++) {
    if (kind[i] === KAIWA && speaker[i]) count.set(speaker[i], (count.get(speaker[i]) || 0) + 1);
  }
  const ranked = [...count.entries()].sort((a, b) => b[1] - a[1]);
  const slots = new Map();
  ranked.slice(0, 3).forEach(([id], k) => slots.set(id, css(`--series-${k + 1}`)));
  return { slots, ranked };
}

function spanColorDetail(i, slots) {
  const { kind, pos, speaker } = BAND.spans;
  if (kind[i] === NOTATION) return css("--notation");
  if (kind[i] === JINOMON) return css("--jinomon");
  if (overlay === "off") return pos[i] % 2 === 0 ? css("--alt-a") : css("--alt-b");
  const sp = speaker[i];
  if (!sp) return css("--unpainted");                       // 不明は塗らない
  if (overlay === "all") return slots.get(sp) || css("--series-other");
  return sp === overlay ? css("--series-1") : css("--unpainted");
}

function chapterSpanRange(ch) {
  const { start } = BAND.spans;
  let lo = 0, hi = start.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (start[m] < ch.start) lo = m + 1; else hi = m; }
  let end = lo;
  while (end < start.length && start[end] < ch.end) end++;
  return [lo, end];
}

/* ---- 俯瞰 ---------------------------------------------------------------- */

function drawOverview(canvas, ch) {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(canvas.clientWidth));
  const h = Math.round(canvas.clientHeight);
  canvas.width = w * dpr; canvas.height = h * dpr;
  const g = canvas.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);

  const cpp = ch.chars / w;
  const acc = new Float64Array(w * 3);
  const weighted = new Float64Array(w);
  const { start, lens, plain, kind } = BAND.spans;
  const [i0, i1] = chapterSpanRange(ch);

  // 位置は原文長、量と色は**可読長**で重み付けする。
  // 表ビューに出す会話率と、帯が見せる比率をずらさないため
  for (let i = i0; i < i1; i++) {
    const s = start[i] - ch.start, e = s + lens[i];
    const share = lens[i] > 0 ? plain[i] / lens[i] : 0;
    const x0 = Math.max(0, Math.floor(s / cpp)), x1 = Math.min(w, Math.ceil(e / cpp));
    for (let x = x0; x < x1; x++) {
      const ov = Math.min(e, (x + 1) * cpp) - Math.max(s, x * cpp);
      if (ov <= 0) continue;
      acc[x * 3 + kind[i]] += ov * share;
      if (kind[i] === KAIWA) weighted[x] += ov * share * plain[i];
    }
  }

  // 1 px ごとに 地の文 / 記法 / 会話 を積む(比率は厳密。混色はしない)
  const colJinomon = css("--jinomon"), colNotation = css("--notation");
  for (let x = 0; x < w; x++) {
    const j = acc[x * 3 + JINOMON], k = acc[x * 3 + KAIWA], n = acc[x * 3 + NOTATION];
    const tot = j + k + n;
    if (tot <= 0) continue;
    const hj = (j / tot) * h, hn = (n / tot) * h, hk = (k / tot) * h;
    let y = h;
    g.fillStyle = colJinomon; g.fillRect(x, y - hj, 1, hj); y -= hj;
    g.fillStyle = colNotation; g.fillRect(x, y - hn, 1, hn); y -= hn;
    g.fillStyle = rampColor(k > 0 ? weighted[x] / k : 0); g.fillRect(x, y - hk, 1, hk);
  }

  // 選択中の話者の出現位置を細いティックで重ねる(帰属できた位置のみ)
  if (overlay !== "off" && overlay !== "all") {
    const { speaker } = BAND.spans;
    g.fillStyle = css("--series-1");
    for (let i = i0; i < i1; i++) {
      if (kind[i] !== KAIWA || speaker[i] !== overlay) continue;
      const x = Math.floor((start[i] - ch.start) / cpp);
      g.fillRect(x, 0, Math.max(1, Math.round(lens[i] / cpp)), 3);
    }
  }
}

/* ---- 詳細 ---------------------------------------------------------------- */

function detailRows(ch, w) {
  return Math.ceil(ch.chars / (w * CHARS_PER_PX));
}

function drawDetail(canvas, ch, slots) {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round(canvas.clientWidth));
  const rows = detailRows(ch, w);
  const h = rows * (DETAIL_ROW_H + DETAIL_ROW_GAP);
  canvas.style.height = h + "px";
  canvas.width = w * dpr; canvas.height = h * dpr;
  const g = canvas.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);

  const perRow = w * CHARS_PER_PX;
  const { start, lens } = BAND.spans;
  const [i0, i1] = chapterSpanRange(ch);
  for (let i = i0; i < i1; i++) {
    g.fillStyle = spanColorDetail(i, slots);
    let s = start[i] - ch.start;
    let remain = lens[i];
    while (remain > 0) {
      const row = Math.floor(s / perRow);
      const col = s - row * perRow;
      const take = Math.min(remain, perRow - col);
      const x = col / CHARS_PER_PX, wpx = Math.max(0.6, take / CHARS_PER_PX);
      g.fillRect(x, row * (DETAIL_ROW_H + DETAIL_ROW_GAP), wpx, DETAIL_ROW_H);
      s += take; remain -= take;
    }
  }
}

/** 詳細キャンバス上の座標 → 本文オフセット(F-17 の起点) */
function offsetAtDetail(canvas, ch, px, py) {
  const w = Math.round(canvas.clientWidth);
  const perRow = w * CHARS_PER_PX;
  const row = Math.floor(py / (DETAIL_ROW_H + DETAIL_ROW_GAP));
  const off = ch.start + row * perRow + Math.floor(px * CHARS_PER_PX);
  return Math.min(ch.end - 1, Math.max(ch.start, off));
}

function spanAt(offset) {
  const { start, lens } = BAND.spans;
  let lo = 0, hi = start.length - 1, best = 0;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (start[m] <= offset) { best = m; lo = m + 1; } else hi = m - 1;
  }
  return offset < start[best] + lens[best] ? best : -1;
}

function describe(offset) {
  const i = spanAt(offset);
  if (i < 0) return "";
  const { kind, plain, run, pos, speaker } = BAND.spans;
  const ch = BAND.chapters.find((c) => c.start <= offset && offset < c.end);
  const head = `第${ch ? ch.label : "?"}章 ${offset.toLocaleString()} 字目`;
  if (kind[i] === NOTATION) return `${head}／記法(章見出し等)`;
  if (kind[i] === JINOMON) return `${head}／地の文 ${plain[i].toLocaleString()} 字`;
  const who = speaker[i] ? BAND.persons[speaker[i]] : "話者不明";
  return `${head}／会話 ${plain[i].toLocaleString()} 字・塊 #${run[i]} の ${pos[i] + 1} 番目／${who}`;
}

/* ---- 組み立て ------------------------------------------------------------ */

function fmt(n) { return n.toLocaleString(); }

function buildTiles() {
  const a = BAND.attribution;
  const utt = a.utterances;
  const runs = BAND.chapters.reduce((s, c) => s + c.runs, 0);
  const tiles = [
    [fmt(BAND.body_chars), "本文の文字数"],
    [fmt(utt), "発話"],
    [fmt(runs), "会話塊"],
    [(a.rate * 100).toFixed(1) + "%", `話者が付く発話(適合率 ${a.precision.toFixed(3)})`],
  ];
  document.getElementById("tiles").innerHTML = tiles
    .map(([v, k]) => `<div class="tile"><div class="v">${v}</div><div class="k">${k}</div></div>`)
    .join("");
}

function buildRows() {
  const list = document.getElementById("bands");
  list.innerHTML = BAND.chapters
    .map(
      (c) => `<div class="band-row" role="button" tabindex="0" data-ch="${c.index}"
                   aria-expanded="false" aria-label="第${c.label}章を開く">
        <div class="ch">第${c.label}章</div>
        <canvas data-ch="${c.index}"></canvas>
        <div class="nums">会話 ${(c.kaiwa_ratio * 100).toFixed(1)}%
          ・塊長 ${c.run_len_mean.toFixed(1)}
          ・塊内 ${(c.in_run_ratio * 100).toFixed(0)}%
          ・交替 ${c.turns_per_1000.toFixed(1)}/千字</div>
      </div>`
    )
    .join("");
  list.querySelectorAll(".band-row").forEach((row) => {
    row.addEventListener("click", () => toggleChapter(+row.dataset.ch));
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleChapter(+row.dataset.ch); }
    });
    row.addEventListener("focus", () => {
      const c = BAND.chapters[+row.dataset.ch - 1];
      say(`第${c.label}章 ${fmt(c.chars)} 字・発話 ${fmt(c.utterances)}・会話塊 ${fmt(c.runs)}`
        + `・発話長 中央 ${c.utterance_len_median} / 最大 ${fmt(c.utterance_len_max)} 字`);
    });
  });
}

function say(msg) { document.getElementById("readout").textContent = msg; }

function toggleChapter(index) {
  openChapter = openChapter === index ? null : index;
  renderDetail();
  document.querySelectorAll(".band-row").forEach((r) => {
    r.setAttribute("aria-expanded", String(+r.dataset.ch === openChapter));
  });
}

function renderDetail() {
  const host = document.getElementById("detail");
  if (openChapter === null) {
    host.innerHTML = `<p class="note">章の帯をクリックすると、その章が 4 字/px で開きます
      (1 発話 ≒ 6px。ここで初めて濃淡の交互が見えます)。</p>`;
    return;
  }
  const c = BAND.chapters[openChapter - 1];
  host.innerHTML = `<h3>第${c.label}章 — 4 字/px</h3>
    <p class="note">地の文は無彩、会話は<strong>塊の中で濃淡を交互に</strong>。
      交互が主張するのは「前の発話と話者が違う」ことだけで、誰かは主張しません
      (鉤括弧の境界が証拠)。長広舌は一枚岩、応酬は縞になります。
      クリックでリーダーの該当位置へ移動します。</p>
    <canvas id="detailCanvas" tabindex="0" aria-label="第${c.label}章の詳細帯"></canvas>`;
  const canvas = document.getElementById("detailCanvas");
  const { slots } = speakerSlots();
  drawDetail(canvas, c, slots);
  canvas.addEventListener("mousemove", (e) => {
    const r = canvas.getBoundingClientRect();
    say(describe(offsetAtDetail(canvas, c, e.clientX - r.left, e.clientY - r.top)));
  });
  canvas.addEventListener("mouseleave", () => say(""));
  canvas.addEventListener("focus", () => say(describe(c.start)));
  canvas.addEventListener("click", (e) => {
    const r = canvas.getBoundingClientRect();
    const off = offsetAtDetail(canvas, c, e.clientX - r.left, e.clientY - r.top);
    location.href = `reader.html?ch=${c.index}&pos=${off}`;
  });
}

function buildLegend() {
  const { ranked } = speakerSlots();
  const structural = [
    ["--jinomon", "地の文"],
    ["--notation", "記法(章見出し等)"],
  ]
    .map(([v, l]) => `<span class="item"><i class="sw" style="background:var(${v})"></i>${l}</span>`)
    .join("");
  const ramp = `<span class="item ramp">会話(俯瞰): 平均発話長
      <span class="bar">${[0, 1, 2, 3, 4]
        .map((i) => `<i style="background:var(--kaiwa-${i})"></i>`)
        .join("")}</span>短い→長い</span>`;
  const alt = `<span class="item"><i class="sw" style="background:var(--alt-a)"></i>
      <i class="sw" style="background:var(--alt-b)"></i>会話(詳細): 塊内の交互</span>`;
  let people = "";
  if (overlay === "all") {
    people = ranked.slice(0, 3)
      .map(([id], k) => `<span class="item"><i class="sw" style="background:var(--series-${k + 1})"></i>${BAND.persons[id]}</span>`)
      .join("") +
      `<span class="item"><i class="sw" style="background:var(--series-other)"></i>その他の話者</span>` +
      `<span class="item"><i class="sw" style="background:var(--unpainted)"></i>話者不明(塗らない)</span>`;
  } else if (overlay !== "off") {
    people = `<span class="item"><i class="sw" style="background:var(--series-1)"></i>${BAND.persons[overlay]}</span>`
      + `<span class="item"><i class="sw" style="background:var(--unpainted)"></i>それ以外・不明</span>`;
  }
  document.getElementById("legend").innerHTML = structural + ramp + alt + people;
}

function buildTable() {
  const rows = BAND.chapters
    .map(
      (c) => `<tr><td>第${c.label}章</td><td>${fmt(c.chars)}</td>
        <td>${(c.kaiwa_ratio * 100).toFixed(1)}</td><td>${fmt(c.utterances)}</td>
        <td>${fmt(c.runs)}</td><td>${c.run_len_mean.toFixed(1)}</td><td>${c.run_len_max}</td>
        <td>${(c.in_run_ratio * 100).toFixed(0)}</td><td>${c.turns_per_1000.toFixed(1)}</td>
        <td>${c.utterance_len_median}</td><td>${fmt(c.utterance_len_max)}</td>
        <td>${(c.attribution_rate * 100).toFixed(0)}</td></tr>`
    )
    .join("");
  document.getElementById("tableBody").innerHTML = rows;
}

function buildSpeakerFilter() {
  const { ranked } = speakerSlots();
  const sel = document.getElementById("overlay");
  sel.innerHTML =
    `<option value="off">重ねない(応酬の構造だけ)</option>` +
    `<option value="all">上位 3 話者 + その他</option>` +
    ranked.map(([id, n]) => `<option value="${id}">${BAND.persons[id]}(${n} 件)</option>`).join("");
  sel.addEventListener("change", () => {
    overlay = sel.value;
    renderAll();
  });
}

function renderAll() {
  document.querySelectorAll(".band-row canvas").forEach((cv) => {
    drawOverview(cv, BAND.chapters[+cv.dataset.ch - 1]);
  });
  renderDetail();
  buildLegend();
}

async function main() {
  BAND = await (await fetch("data/band.json")).json();
  document.getElementById("work").textContent = `${BAND.title}／${BAND.author}`;
  buildTiles();
  buildRows();
  buildSpeakerFilter();
  buildTable();
  renderAll();
  let t;
  window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(renderAll, 120); });
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", renderAll);
}

main();
