/* リーダー(F-16)と帯からの位置決め(F-17)
 *
 * 段落は body_raw 上の開始オフセットを持ち、各項目は原文で消費する文字数 raw を持つ。
 * 話者の色は帯索引の span に**厳密に沿って**塗る — 1 つのテキスト項目が発話境界を
 * またぐことがあるので、項目の先頭だけで会話/地の文を決めてはならない(L4 で発覚)。
 */

const KAIWA = 1;

const params = new URLSearchParams(location.search);
const chIndex = Math.min(11, Math.max(1, parseInt(params.get("ch") || "1", 10)));
const target = params.get("pos") === null ? null : parseInt(params.get("pos"), 10);

let BAND = null;

function esc(s) {
  return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
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

function speakerAt(offset) {
  const i = spanAt(offset);
  if (i < 0 || BAND.spans.kind[i] !== KAIWA) return null;
  return BAND.spans.speaker[i];
}

function markup(text, speaker) {
  if (!speaker) return esc(text);
  const name = BAND.persons[speaker] || speaker;
  return `<mark title="${esc(name)}">${esc(text)}</mark>`;
}

/** テキスト項目を span 境界で切りながら描く。表示長 == raw(置換は 1:1)。 */
function renderText(text, offStart) {
  const { start, lens } = BAND.spans;
  let html = "", i = 0;
  while (i < text.length) {
    const off = offStart + i;
    const si = spanAt(off);
    const spanEnd = si >= 0 ? start[si] + lens[si] : offStart + text.length;
    const take = Math.max(1, Math.min(text.length - i, spanEnd - off));
    html += markup(text.slice(i, i + take), speakerAt(off));
    i += take;
  }
  return html;
}

function renderParagraph(p) {
  let off = p.start;
  let html = "";
  const leadKaiwa = spanAt(p.start) >= 0 && BAND.spans.kind[spanAt(p.start)] === KAIWA;
  for (const it of p.items) {
    const raw = it[it.length - 1];
    if (it[0] === "n") { off += raw; continue; }      // 入力者注は描かないが原文は進む
    if (it[0] === "r") {
      const base = `<ruby>${esc(it[1])}<rt>${esc(it[2])}</rt></ruby>`;
      const sp = speakerAt(off);
      html += sp ? `<mark title="${esc(BAND.persons[sp] || sp)}">${base}</mark>` : base;
    } else {
      html += renderText(it[1], off);
    }
    off += raw;
  }
  return { html, leadKaiwa, start: p.start, end: off };
}

function buildNav() {
  document.getElementById("nav").innerHTML = BAND.chapters
    .map((c) => `<a href="reader.html?ch=${c.index}"${c.index === chIndex ? ' aria-current="page"' : ""}>第${c.label}章</a>`)
    .join("");
}

async function main() {
  BAND = await (await fetch("data/band.json")).json();
  const shard = await (await fetch(`data/text/ch${String(chIndex).padStart(2, "0")}.json`)).json();
  const c = BAND.chapters[chIndex - 1];

  document.title = `第${c.label}章 — 猫アトラス`;
  document.getElementById("work").textContent = `${BAND.title}／${BAND.author}`;
  document.getElementById("chapterTitle").textContent = `第${c.label}章`;
  document.getElementById("chapterMeta").textContent =
    `${c.chars.toLocaleString()} 字・発話 ${c.utterances.toLocaleString()}`
    + `・会話 ${(c.kaiwa_ratio * 100).toFixed(1)}%`
    + `・話者が付く発話 ${(c.attribution_rate * 100).toFixed(0)}%`
    + `(色が付くのはその分だけ。不明は塗っていません)`;
  buildNav();

  const host = document.getElementById("body");
  let hitId = null;
  host.innerHTML = shard.paragraphs
    .map((p, k) => {
      const r = renderParagraph(p);
      const hit = target !== null && p.start <= target && target < r.end;
      if (hit && hitId === null) hitId = `p${k}`;
      return `<p id="p${k}" class="anchor${r.leadKaiwa ? " kaiwa-lead" : ""}${hit ? " hit" : ""}"
                 data-start="${p.start}">${r.html}</p>`;
    })
    .join("");

  if (hitId) {
    const el = document.getElementById(hitId);
    el.scrollIntoView({ block: "center" });
    document.getElementById("jumped").textContent =
      `帯の ${target.toLocaleString()} 字目から移動しました(印の段落は本文 ${Number(el.dataset.start).toLocaleString()} 字目から)。`;
  } else if (target !== null) {
    document.getElementById("jumped").textContent =
      `${target.toLocaleString()} 字目は段落の外(章見出し等の記法)です。`;
  }

  if (shard.notes_not_rendered) {
    document.getElementById("limits").textContent =
      `この章の入力者注 ${shard.notes_not_rendered} 件は描画していません(ルビと外字のみ再現)。`;
  }
}

main();
