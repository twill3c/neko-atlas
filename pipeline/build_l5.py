"""L5 の成果物を生成する。

  data/chrono.json  — 章を単位とした文体距離・PCA・rolling delta・初出年月(F-18)
  data/futakoe.json — 地の文 / 会話文の対比(F-19)
  data/haichi.json  — 語彙分散(F-20)
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np

from .dispersion import collect, occurrences, rank_concentrated, token_stream
from .stylometry import (
    BLOCK_ALL,
    BLOCK_JINOMON,
    BLOCK_KAIWA,
    MFW,
    STEP,
    WINDOW,
    block_delta,
    burrows_delta,
    load_tokens_by_chapter,
    relative_freq,
    rolling_delta,
    size_confound,
)

DATA = Path("data")
WEB = Path("web")


def _delta_block(chapters, pools, voice: str) -> dict:
    names = [f"第{c['label']}章" for c in chapters]
    toks = [pools[c["index"]][voice] for c in chapters]
    r = burrows_delta(names, toks)
    # 各単位が他の全単位からどれだけ離れているか(孤立度)
    m = r.distance.shape[0]
    isolation = [float(r.distance[i].sum() / (m - 1)) for i in range(m)]
    return {
        "voice": voice,
        "units": names,
        "tokens": [len(t) for t in toks],
        "mfw": MFW,
        "features_head": r.features[:40],
        "distance": [[round(float(x), 5) for x in row] for row in r.distance],
        "coords": [[round(float(x), 5) for x in row] for row in r.coords],
        "explained": [round(x, 4) for x in r.explained],
        "isolation": [round(x, 5) for x in isolation],
        "most_isolated": names[int(np.argmax(isolation))],
    }


def build_chrono(chapters, pools) -> dict:
    serial = json.loads((DATA / "serial.json").read_text(encoding="utf-8"))

    # (a) 章をそのまま単位にした素朴版。**解釈には使わない** —
    #     章の大きさが最大 16.6 倍違い、孤立度が語数の関数になるため(HC-025)。
    #     交絡の大きさを見せるためだけに残す
    naive = {}
    for v in ("jinomon", "kaiwa", "all"):
        b = _delta_block(chapters, pools, v)
        b["size_confound_r"] = round(size_confound(b["tokens"], b["isolation"]), 4)
        b["usable"] = abs(b["size_confound_r"]) <= 0.5
        naive[v] = b

    # (b) 等サイズブロックを単位にした版 + ラベル置換検定。**こちらを解釈に使う**
    blocks = {
        "jinomon": block_delta(chapters, pools, "jinomon", BLOCK_JINOMON),
        "kaiwa": block_delta(chapters, pools, "kaiwa", BLOCK_KAIWA),
        "all": block_delta(chapters, pools, "all", BLOCK_ALL),
    }

    # rolling delta は地の文で。素性と基準は章単位の集計と同じものを使う
    names = [f"第{c['label']}章" for c in chapters]
    toks = [pools[c["index"]]["jinomon"] for c in chapters]
    r = burrows_delta(names, toks)
    freqs = np.vstack([relative_freq(t, r.features) for t in toks])
    mean, sd = freqs.mean(axis=0), freqs.std(axis=0, ddof=0)
    sd[sd == 0] = 1.0
    flat: list[str] = []
    bounds = []
    for c in chapters:
        bounds.append({"chapter": c["index"], "label": c["label"], "token": len(flat)})
        flat.extend(pools[c["index"]]["jinomon"])
    roll = rolling_delta(flat, r.features, mean, sd)
    ch1_centroid = ((relative_freq(pools[chapters[0]["index"]]["jinomon"], r.features) - mean) / sd)
    series = [
        {
            "start": w["start"],
            "from_prev": None if w["from_prev"] is None else round(w["from_prev"], 5),
            "from_ch1": round(float(np.abs(w["z"] - ch1_centroid).mean()), 5),
        }
        for w in roll
    ]

    return {
        "mfw": MFW,
        "window": WINDOW,
        "step": STEP,
        "note": "固有名詞は文体指標から除外。置換検定の seed は固定で、再実行で同一の結果になる",
        "method": "章をそのまま単位にすると孤立度が語数の関数になる(HC-025)。"
                  "等サイズブロックを単位に取り直し、章ラベルの置換検定を対照に置いた",
        "naive": naive,
        "blocks": blocks,
        "rolling": {"tokens": len(flat), "chapter_bounds": bounds, "series": series},
        "serial": {
            "issues": serial["footer_issues"],
            "count": serial["count"],
            "chapter_count": serial["chapter_count"],
            "one_to_one": serial["one_to_one"],
            "status": serial["chapter_to_issue_status"],
        },
    }


def build_futakoe(chapters) -> dict:
    stats = json.loads((DATA / "stats.json").read_text(encoding="utf-8"))
    out = {"dicts": {}}
    for name, s in stats.items():
        out["dicts"][name] = {
            "label": s["dict"],
            "license": s["license"],
            "by_voice": {
                v: {
                    k: s["by_voice"][v][k]
                    for k in ("chars", "tokens", "sentences", "sentence_len",
                              "punct_per_100_chars", "goshu_ratio", "pos1_ratio",
                              "pos_bigram_top", "bunmatsu_top")
                }
                for v in ("jinomon", "kaiwa")
            },
            "overall": {
                k: s["overall"][k]
                for k in ("chars", "tokens", "sentences", "sentence_len",
                          "goshu_ratio", "pos1_ratio")
            },
            "by_chapter": [
                {
                    "chapter": e["chapter"],
                    **{
                        v: {
                            "chars": e[v]["chars"],
                            "tokens": e[v]["tokens"],
                            "sentence_len_mean": e[v]["sentence_len"]["mean"],
                            "goshu_ratio": e[v]["goshu_ratio"],
                        }
                        for v in ("jinomon", "kaiwa")
                    },
                }
                for e in s["by_chapter"]
            ],
        }
    return out


def build_haichi(chapters) -> dict:
    band = json.loads((DATA / "band.json").read_text(encoding="utf-8"))
    persons = json.loads((DATA / "persons.json").read_text(encoding="utf-8"))
    stream = token_stream(DATA)
    if stream["consumed_ratio"] < 0.999 or stream["unmatched"] > 0:
        raise SystemExit(f"形態素と本文の整列に失敗: {stream['consumed_ratio']}"
                         f" / 未整列 {stream['unmatched']}")
    collected = collect(stream, chapters)
    ranked = rank_concentrated(collected, chapters)

    alias_terms: dict[str, str] = {}
    for p in persons["persons"]:
        if p["kind"] == "unresolved":
            continue
        for a in p["aliases"]:
            alias_terms[a] = p["display"]

    lemmas = {r["lemma"] for r in ranked} | set(alias_terms)
    hits = occurrences(stream, lemmas)
    return {
        "body_chars": band["body_chars"],
        "chapters": [
            {"index": c["index"], "label": c["label"], "start": c["start"], "end": c["end"]}
            for c in chapters
        ],
        "note": "主題語は手で選ばず、章別分布の偏り(Juilland の D)が小さい順に採った。"
                "感情価曲線は採らない — 筋を持たない作品では機能しないため(F-20)",
        "min_freq": 30,
        "alignment": {k: stream[k] for k in
                      ("plain_chars", "cursor_end", "consumed_ratio", "total_rows", "unmatched")},
        "concentrated": ranked,
        "person_terms": alias_terms,
        "occurrences": {k: v for k, v in hits.items() if v},
    }


def build() -> dict:
    band = json.loads((DATA / "band.json").read_text(encoding="utf-8"))
    chapters = band["chapters"]
    pools = load_tokens_by_chapter(DATA)

    chrono = build_chrono(chapters, pools)
    (DATA / "chrono.json").write_text(
        json.dumps(chrono, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    futakoe = build_futakoe(chapters)
    (DATA / "futakoe.json").write_text(
        json.dumps(futakoe, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    haichi = build_haichi(chapters)
    (DATA / "haichi.json").write_text(
        json.dumps(haichi, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    wd = WEB / "data"
    wd.mkdir(parents=True, exist_ok=True)
    for n in ("chrono.json", "futakoe.json", "haichi.json"):
        shutil.copy(DATA / n, wd / n)
    return {"chrono": chrono, "futakoe": futakoe, "haichi": haichi}


if __name__ == "__main__":
    r = build()
    c = r["chrono"]
    for v in ("jinomon", "kaiwa", "all"):
        b = c["naive"][v]
        print(f"[素朴 {v:8}] サイズ交絡 r={b['size_confound_r']:+.3f}"
              f" → {'使える' if b['usable'] else '解釈に使わない'}")
    for v, b in c["blocks"].items():
        print(f"              PC1 と会話率の相関 r={b['pc1_vs_kaiwa_share_r']:+.3f}"
              if v == "all" else "", end="")
        sig = [x for x in b["chapters"] if b["per_chapter"][x]["p"] < 0.05]
        print(f"[ブロック {v:8}] {b['blocks']} 個(各 {b['block_size']} 語)"
              f"／観測 {b['observed']:+.4f} 帰無 {b['null_mean']:+.4f} p={b['p_value']:.4f}"
              f"／サイズ交絡 r={b['size_confound_r']:+.3f}")
        print(f"              有意に孤立する章: "
              + ("、".join(f"第{x}章(p={b['per_chapter'][x]['p']:.3f})" for x in sig) or "なし"))
    print(f"rolling: 窓 {c['window']}・{len(c['rolling']['series'])} 点")
    h = r["haichi"]
    print("固まって出る語 上位 12:",
          "、".join(f"{x['lemma']}(D={x['d']:.2f}/第{x['peak_chapter']}章)"
                    for x in h["concentrated"][:12]))
    print("分散プロットの語数:", len(h["occurrences"]),
          "／総出現", sum(len(v) for v in h["occurrences"].values()))
