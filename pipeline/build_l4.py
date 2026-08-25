"""L4 の成果物を生成する。

  data/band.json        — 応酬の帯の索引(F-26)
  data/text/ch*.json    — リーダーの章シャード(F-16)
  web/data/*            — 上記を web から参照できる位置へ配置
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .aozora import split_document
from .attribute import attribute, build_alias_table
from .band import chapter_aggregates, check_coverage, build_spans, save as save_band
from .chapters import find_chapters
from .persons import build as build_persons
from .persons import to_json as persons_to_json
from .reader import build_chapter, plain_length
from .reader import save as save_shard
from .voices import split_voices

DATA = Path("data")
WEB = Path("web")


def build() -> dict:
    card_id = json.loads((DATA / "chapters.json").read_text(encoding="utf-8"))["card_id"]
    raw = (DATA / "raw" / f"{card_id}.txt").read_bytes().decode("utf-8")
    doc = split_document(raw)
    chapters, _ = find_chapters(doc)
    voices = split_voices(doc)
    flat = "".join(s.text for s in voices["segments"])
    pj = persons_to_json(build_persons(flat))
    atts = attribute(voices["segments"], chapters, build_alias_table(pj))

    body_chars = len(doc.body_raw)
    spans = build_spans(voices["segments"], body_chars, atts,
                        boundaries=[c.start for c in chapters] + [chapters[-1].end],
                        labels=voices["labels"])
    cov = check_coverage(spans, body_chars)
    if not (cov["covers_body"] and cov["contiguous"] and cov["run_positions_ok"]):
        raise SystemExit(f"帯索引の被覆に失敗: {cov}")

    aggs = chapter_aggregates(chapters, spans)
    attributed = sum(1 for k, s in zip(spans["kind"], spans["speaker"]) if k == 1 and s)
    utterances = sum(1 for k in spans["kind"] if k == 1)

    persons = {p["id"]: p["display"] for p in pj["persons"]}
    persons.update({u["id"]: u["display"] for u in pj["unresolved"]})

    band = {
        "title": doc.title,
        "author": doc.author,
        "body_chars": body_chars,
        "coverage": cov,
        "chapters": aggs,
        "persons": persons,
        "attribution": {
            "utterances": utterances,
            "attributed": attributed,
            "rate": round(attributed / utterances, 4),
            "precision": 0.900,  # docs/attribution_calibration.md の実測(gold 300)
            "gold_size": 300,
            "note": "帰属できた発話だけに話者色を重ねる。不明は塗らない(F-15c)",
        },
        "spans": spans,
    }
    save_band(DATA / "band.json", band)

    shard_info = []
    for c in chapters:
        ch = build_chapter(doc, c.start, c.end)
        ch.update({"chapter": c.index, "label": c.label, "start": c.start, "end": c.end})
        path = DATA / "text" / f"ch{c.index:02d}.json"
        save_shard(path, ch)
        shard_info.append(
            {
                "chapter": c.index,
                "paragraphs": len(ch["paragraphs"]),
                "plain_chars": plain_length(ch),
                "bytes": path.stat().st_size,
            }
        )

    # web から参照できる位置へ配置(静的配信 N-01)
    wd = WEB / "data"
    wd.mkdir(parents=True, exist_ok=True)
    shutil.copy(DATA / "band.json", wd / "band.json")
    (wd / "text").mkdir(exist_ok=True)
    for c in chapters:
        shutil.copy(DATA / "text" / f"ch{c.index:02d}.json", wd / "text" / f"ch{c.index:02d}.json")

    return {"coverage": cov, "chapters": aggs, "shards": shard_info,
            "band_bytes": (DATA / "band.json").stat().st_size}


if __name__ == "__main__":
    r = build()
    c = r["coverage"]
    print("帯索引の被覆:", "成立" if c["covers_body"] else "不成立",
          f"／ span {c['spans']:,}・総和 {c['sum_lens']:,} == 本文長 {c['body_chars']:,}"
          f"・会話塊 {c['runs']:,}")
    print(f"band.json {r['band_bytes']:,} bytes")
    total = sum(s["bytes"] for s in r["shards"])
    print(f"章シャード {len(r['shards'])} 本・計 {total:,} bytes"
          f"(最大 {max(s['bytes'] for s in r['shards']):,})")
    print(f"段落 {sum(s['paragraphs'] for s in r['shards']):,}"
          f"・可読 {sum(s['plain_chars'] for s in r['shards']):,} 字")
