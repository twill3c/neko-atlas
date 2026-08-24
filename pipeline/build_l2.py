"""L2 の成果物を生成する。

  data/voices.json          — 二声分離と直和検査(O-2)
  data/morph/{dict}/ch*.json — 章単位の形態素シャード(2 辞書ぶん)
  data/dict_diff.jsonl      — 二辞書の差分の全件(O-5)
  docs/dict_diff.md         — その要約(全件は jsonl 側)
  data/stats.json           — 語種・文長・句読点・品詞・文末表現(声別・章別)
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

from .aozora import split_document
from .chapters import find_chapters
from .morph import Analyzer, diff_segmentation, load_analyzers
from .stats import check_composition, summarize
from .voices import Segment, check_direct_sum, save, split_voices

DATA = Path("data")
DOCS = Path("docs")


def load_document():
    card_id = json.loads((DATA / "chapters.json").read_text(encoding="utf-8"))["card_id"]
    raw = (DATA / "raw" / f"{card_id}.txt").read_bytes().decode("utf-8")
    return card_id, split_document(raw)


def segments_by_chapter(chapters, segments: list[Segment]) -> dict[int, list[Segment]]:
    out: dict[int, list[Segment]] = collections.defaultdict(list)
    for seg in segments:
        ch = next((c.index for c in chapters if c.start <= seg.start < c.end), 0)
        out[ch].append(seg)
    return out


def build() -> dict:
    card_id, doc = load_document()
    chapters, _ = find_chapters(doc)

    voices = split_voices(doc)
    check = check_direct_sum(voices)
    save(voices, DATA / "voices.json")
    if not (check["covers_body"] and check["segments_cover_content"]):
        raise SystemExit(f"O-2 直和検査に失敗: {check}")

    analyzers = load_analyzers()
    by_ch = segments_by_chapter(chapters, voices["segments"])

    diffs_path = DATA / "dict_diff.jsonl"
    diff_counter: collections.Counter = collections.Counter()
    diff_examples: dict[str, dict] = {}
    total_diffs = 0

    stats: dict = {a.spec.name: {"dict": a.spec.label, "license": a.spec.license,
                                 "by_chapter": [], "by_voice": {}, "overall": {}}
                   for a in analyzers}
    pools: dict[str, dict[str, list]] = {
        a.spec.name: {"jinomon": [], "kaiwa": [], "jinomon_text": [], "kaiwa_text": []}
        for a in analyzers
    }

    with diffs_path.open("w", encoding="utf-8") as diff_fp:
        for ch in sorted(by_ch):
            segs = by_ch[ch]
            per_dict_tokens: dict[str, dict[str, list]] = {}
            for a in analyzers:
                rows = []
                voice_tokens = {"jinomon": [], "kaiwa": []}
                for si, seg in enumerate(segs):
                    toks = a.tokenize(seg.text)
                    voice_tokens[seg.kind].extend(toks)
                    for t in toks:
                        rows.append([t.surface, t.pos1, t.pos2, t.lemma, t.goshu, t.cform,
                                     seg.kind, si])
                shard = DATA / "morph" / a.spec.name / f"ch{ch:02d}.json"
                shard.parent.mkdir(parents=True, exist_ok=True)
                shard.write_text(
                    json.dumps(
                        {"chapter": ch, "dict": a.spec.name,
                         "cols": ["s", "pos1", "pos2", "lemma", "goshu", "cform", "voice", "seg"],
                         "rows": rows},
                        ensure_ascii=False, separators=(",", ":"),
                    ),
                    encoding="utf-8",
                )
                per_dict_tokens[a.spec.name] = voice_tokens
                for kind in ("jinomon", "kaiwa"):
                    pools[a.spec.name][kind].extend(voice_tokens[kind])

            for kind in ("jinomon", "kaiwa"):
                text = "".join(s.text for s in segs if s.kind == kind)
                for a in analyzers:
                    pools[a.spec.name][f"{kind}_text"].append(text)

            chapter_entry = {}
            for a in analyzers:
                chapter_entry[a.spec.name] = {
                    kind: summarize(
                        per_dict_tokens[a.spec.name][kind],
                        "".join(s.text for s in segs if s.kind == kind),
                    )
                    for kind in ("jinomon", "kaiwa")
                }
                stats[a.spec.name]["by_chapter"].append(
                    {"chapter": ch, **chapter_entry[a.spec.name]}
                )

            # O-5: 同一入力に対する 2 辞書の差分を全件書き出す
            gen, kin = analyzers[0], analyzers[1]
            for si, seg in enumerate(segs):
                d = diff_segmentation(seg.text, gen.tokenize(seg.text), kin.tokenize(seg.text))
                for item in d:
                    total_diffs += 1
                    key = (
                        "/".join(x["s"] for x in item["gendai"])
                        + " || "
                        + "/".join(x["s"] for x in item["kindai"])
                    )
                    diff_counter[key] += 1
                    diff_examples.setdefault(key, item)
                    diff_fp.write(
                        json.dumps({"chapter": ch, "segment": si, "voice": seg.kind,
                                    "body_offset": seg.start, **item},
                                   ensure_ascii=False, separators=(",", ":")) + "\n"
                    )

    for a in analyzers:
        name = a.spec.name
        parts = []
        for kind in ("jinomon", "kaiwa"):
            s = summarize(pools[name][kind], "".join(pools[name][f"{kind}_text"]))
            stats[name]["by_voice"][kind] = s
            parts.append(s)
        all_tokens = pools[name]["jinomon"] + pools[name]["kaiwa"]
        all_text = "".join(pools[name]["jinomon_text"] + pools[name]["kaiwa_text"])
        overall = summarize(all_tokens, all_text)
        stats[name]["overall"] = overall
        stats[name]["composition_check"] = check_composition(overall, parts)

    (DATA / "stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    write_dict_diff_doc(analyzers, total_diffs, diff_counter, diff_examples, voices)
    return {"check": check, "total_diffs": total_diffs, "stats": stats, "voices": voices}


def write_dict_diff_doc(analyzers, total, counter, examples, voices) -> None:
    tokens_gendai = None
    lines = [
        "# dict_diff — 二辞書照合(O-5)の全件記録",
        "",
        "**このファイルは実測の出力であり、手で書かない。**",
        "",
        "| 辞書 | 版 | ライセンス |",
        "|---|---|---|",
    ]
    for a in analyzers:
        lines.append(f"| {a.spec.label} | {a.spec.version} | {a.spec.license} |")
    lines += [
        "",
        "近代文語 UniDic は **CC BY-NC-SA 4.0**。辞書そのものは再配布しない(`.dict/` は git 管理外)。",
        "本アプリが配るのは解析の派生値のみ。",
        "",
        "## 差分の総量",
        "",
        f"- 差分区間: **{total:,} 件**(全件は `data/dict_diff.jsonl`)",
        f"- 異なりパターン: **{len(counter):,} 種**",
        "",
        "**差分率に閾値は課さない。** 差分そのものがこの作品の混成性の測定値である。",
        "",
        "## 頻出パターン(上位 40)",
        "",
        "| 現代書き言葉 UniDic | 近代文語 UniDic | 件数 |",
        "|---|---|---|",
    ]
    for key, n in counter.most_common(40):
        left, right = key.split(" || ")
        lines.append(f"| `{left}` | `{right}` | {n:,} |")
    lines += [
        "",
        "## 二声別の差分(参考)",
        "",
        "地の文と会話文で差分の出方が違うかどうかは `data/dict_diff.jsonl` の `voice` 列で集計できる。",
        "",
    ]
    DOCS.mkdir(exist_ok=True)
    (DOCS / "dict_diff.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    r = build()
    c = r["check"]
    print("O-2 直和検査:", "成立" if c["covers_body"] and c["segments_cover_content"] else "不成立")
    print("  区分:", c["counts"], "／ 総和", c["sum"], "== 本文長", c["body_chars"])
    print("  未対応括弧:", c["unclosed_count"], "／ 会話比率", c["kaiwa_ratio"])
    print("O-5 二辞書差分:", f"{r['total_diffs']:,} 件")
    for name, s in r["stats"].items():
        comp = s["composition_check"]
        print(f"  [{name}] 合成検算 {comp} ／ 語種(地の文)",
              {k: v for k, v in list(s["by_voice"]["jinomon"]["goshu_ratio"].items())[:4]})
