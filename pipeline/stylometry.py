"""F-18 — 章(連載回)を単位とした文体距離。

Burrows's Delta:
  1. コーパス全体で最頻語 (MFW) を N 語選ぶ
  2. 各単位の相対頻度を、コーパスの平均・標準偏差で z 化する
  3. 2 単位間の距離 = z の差の絶対値の平均

規律:
- **地の文と会話文で別々に測る。** 章によって会話率が 11%〜78% と極端に振れるので、
  全文で測ると「文体」ではなく「会話率」を測ることになる(F-19 の実演材料でもある)
- 乱数を使わない(PCA は共分散行列の固有分解。N-06 の再現性)
"""
from __future__ import annotations

import collections
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MFW = 200          # 最頻語の数
WINDOW = 3000      # rolling delta の窓(形態素)
STEP = 1000

#: 文体の指標にしない品詞(固有名詞は話題を拾ってしまう)
EXCLUDED_POS2 = ("固有名詞",)


@dataclass
class DeltaResult:
    units: list[str]
    features: list[str]
    z: np.ndarray          # (unit, feature)
    distance: np.ndarray   # (unit, unit)
    coords: np.ndarray     # PCA 第 1・2 主成分
    explained: list[float]


def select_mfw(token_lists: list[list[str]], n: int = MFW) -> list[str]:
    """全単位を合算した頻度で MFW を選ぶ。同順位は語形で決めて再現性を保つ。"""
    total: collections.Counter = collections.Counter()
    for toks in token_lists:
        total.update(toks)
    ranked = sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))
    return [w for w, _ in ranked[:n]]


def relative_freq(tokens: list[str], features: list[str]) -> np.ndarray:
    c = collections.Counter(tokens)
    n = max(1, len(tokens))
    return np.array([c[f] / n for f in features], dtype=float)


def burrows_delta(unit_names: list[str], token_lists: list[list[str]], n_mfw: int = MFW) -> DeltaResult:
    features = select_mfw(token_lists, n_mfw)
    freqs = np.vstack([relative_freq(t, features) for t in token_lists])
    mean = freqs.mean(axis=0)
    sd = freqs.std(axis=0, ddof=0)
    sd[sd == 0] = 1.0                      # 全単位で同値の素性は寄与 0 にする
    z = (freqs - mean) / sd

    m = len(unit_names)
    dist = np.zeros((m, m))
    for i in range(m):
        for j in range(m):
            dist[i, j] = np.abs(z[i] - z[j]).mean()

    coords, explained = pca2(z)
    return DeltaResult(unit_names, features, z, dist, coords, explained)


def pca2(z: np.ndarray) -> tuple[np.ndarray, list[float]]:
    """第 1・2 主成分。乱数を使わない(共分散行列の固有分解)。

    符号は「第 1 単位の座標が非負」になるよう正規化する — 実行ごとに向きが
    反転しないようにするため(N-06)。
    """
    centered = z - z.mean(axis=0)
    cov = np.cov(centered, rowvar=False)
    vals, vecs = np.linalg.eigh(cov)
    order = np.argsort(vals)[::-1]
    vals, vecs = vals[order], vecs[:, order]
    coords = centered @ vecs[:, :2]
    for k in range(coords.shape[1]):
        if coords[0, k] < 0:
            coords[:, k] *= -1
    total = float(vals.sum()) or 1.0
    return coords, [float(vals[0] / total), float(vals[1] / total)]


def rolling_delta(tokens: list[str], features: list[str], mean: np.ndarray, sd: np.ndarray,
                  window: int = WINDOW, step: int = STEP) -> list[dict]:
    """窓を滑らせて、直前の窓との文体距離と、先頭章の重心からの距離を測る。"""
    out = []
    prev = None
    for start in range(0, max(1, len(tokens) - window + 1), step):
        chunk = tokens[start : start + window]
        z = (relative_freq(chunk, features) - mean) / sd
        out.append({"start": start, "z": z, "from_prev": None if prev is None
                    else float(np.abs(z - prev).mean())})
        prev = z
    return out


def load_tokens_by_chapter(data_dir: Path, dict_name: str = "gendai") -> dict:
    """章別・声別の lemma 列を読む。固有名詞は文体指標から外す。"""
    by_ch: dict[int, dict[str, list[str]]] = {}
    for path in sorted((data_dir / "morph" / dict_name).glob("ch*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        cols = {c: i for i, c in enumerate(d["cols"])}
        pools = {"jinomon": [], "kaiwa": [], "all": [], "all_voice": []}
        for row in d["rows"]:
            pos1, pos2 = row[cols["pos1"]], row[cols["pos2"]]
            if pos2 in EXCLUDED_POS2 or pos1 in ("補助記号", "空白"):
                continue
            lemma = row[cols["lemma"]] or row[cols["s"]]
            voice = row[cols["voice"]]
            pools[voice].append(lemma)
            pools["all"].append(lemma)
            pools["all_voice"].append(voice)
        by_ch[d["chapter"]] = pools
    return by_ch


# --- 等サイズ化(HC-025)-------------------------------------------------------

BLOCK_JINOMON = 2000   # 地の文の等サイズブロック(形態素)
BLOCK_KAIWA = 1200     # 会話文の等サイズブロック
BLOCK_ALL = 2000       # 全文(地の文 + 会話)の等サイズブロック


def split_blocks(tokens: list[str], size: int) -> list[list[str]]:
    """先頭から等サイズに切る。端数は捨てる — **大きさを揃えることが目的**なので。"""
    n = len(tokens) // size
    return [tokens[i * size : (i + 1) * size] for i in range(n)]


def size_confound(sizes: list[int], stat: list[float]) -> float:
    """統計量が単位の大きさの関数になっていないかを測る(log サイズとの相関)。"""
    if len(sizes) < 3:
        return 0.0
    x = np.log(np.array(sizes, dtype=float))
    y = np.array(stat, dtype=float)
    if x.std() == 0 or y.std() == 0:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


PERM_SEED = 20260825
PERM_N = 2000


def block_delta(chapters, pools, voice: str, size: int) -> dict:
    """**等サイズブロックを単位に** Delta を測る。章はブロックのラベルとして扱う。

    統計は**ブロック対の水準**で取る(重心を作らない) — 重心はブロック数が多いほど
    平滑化され、ブロック数の少ない章が必ず遠く見えるため(HC-025)。

      within[c]  = 章 c の中のブロック対の平均距離
      between[c] = 章 c のブロックと他章のブロックの平均距離

    対照はラベル置換検定。章のラベルを混ぜて同じ統計を取り、観測値が帰無分布の
    どこに位置するかを見る。**seed を固定する**(N-06)。
    """
    labels: list[str] = []
    blocks: list[list[str]] = []
    kaiwa_share: list[float] = []
    for c in chapters:
        toks = pools[c["index"]][voice]
        voices = pools[c["index"]].get("all_voice") if voice == "all" else None
        for k, b in enumerate(split_blocks(toks, size)):
            labels.append(str(c["index"]))
            blocks.append(b)
            if voices is not None:
                seg = voices[k * size : (k + 1) * size]
                kaiwa_share.append(sum(1 for v in seg if v == "kaiwa") / max(1, len(seg)))
            else:
                kaiwa_share.append(1.0 if voice == "kaiwa" else 0.0)
    if len(blocks) < 6:
        return {"voice": voice, "block_size": size, "blocks": len(blocks),
                "note": "ブロックが足りず等サイズ比較ができない"}

    features = select_mfw(blocks, MFW)
    freqs = np.vstack([relative_freq(b, features) for b in blocks])
    mean, sd = freqs.mean(axis=0), freqs.std(axis=0, ddof=0)
    sd[sd == 0] = 1.0
    z = (freqs - mean) / sd

    n = len(blocks)
    dist = np.zeros((n, n))
    for i in range(n):
        dist[i] = np.abs(z - z[i]).mean(axis=1)
    coords, explained = pca2(z)

    lab = np.array(labels)

    def pair_stats(assign: np.ndarray) -> tuple[dict, float, float]:
        w_all, b_all = [], []
        per: dict[str, dict] = {}
        for c in np.unique(assign):
            ii = np.where(assign == c)[0]
            jj = np.where(assign != c)[0]
            wp = [dist[a, b] for k, a in enumerate(ii) for b in ii[k + 1:]]
            bp = dist[np.ix_(ii, jj)].ravel() if len(jj) else np.array([])
            per[str(c)] = {
                "within": float(np.mean(wp)) if wp else None,
                "between": float(np.mean(bp)) if bp.size else None,
                "blocks": int(len(ii)),
            }
            w_all.extend(wp)
            b_all.extend(bp.tolist())
        return per, (float(np.mean(w_all)) if w_all else 0.0), (float(np.mean(b_all)) if b_all else 0.0)

    per, within_all, between_all = pair_stats(lab)
    observed = between_all - within_all

    rng = np.random.default_rng(PERM_SEED)
    null = np.empty(PERM_N)
    per_null: dict[str, list[float]] = {c: [] for c in per}
    for t in range(PERM_N):
        shuffled = rng.permutation(lab)
        p2, w2, b2 = pair_stats(shuffled)
        null[t] = b2 - w2
        for c in per_null:
            v = p2.get(c, {}).get("between")
            if v is not None:
                per_null[c].append(v)

    p_global = float((np.sum(null >= observed) + 1) / (PERM_N + 1))
    chs = [str(c["index"]) for c in chapters if str(c["index"]) in per]
    for c in chs:
        obs = per[c]["between"]
        nulls = np.array(per_null[c]) if per_null[c] else np.array([obs])
        per[c]["p"] = float((np.sum(nulls >= obs) + 1) / (len(nulls) + 1))
        per[c]["null_mean"] = round(float(nulls.mean()), 5)
        per[c]["between"] = round(obs, 5)
        per[c]["within"] = None if per[c]["within"] is None else round(per[c]["within"], 5)

    counts = [per[c]["blocks"] for c in chs]
    return {
        "voice": voice,
        "block_size": size,
        "blocks": n,
        "chapters": chs,
        "block_counts": counts,
        "labels": labels,
        "coords": [[round(float(x), 5) for x in row] for row in coords],
        "explained": [round(x, 4) for x in explained],
        "per_chapter": {c: per[c] for c in chs},
        "within_all": round(within_all, 5),
        "between_all": round(between_all, 5),
        "observed": round(observed, 5),
        "null_mean": round(float(null.mean()), 5),
        "null_sd": round(float(null.std()), 5),
        "p_value": round(p_global, 5),
        "permutations": PERM_N,
        "seed": PERM_SEED,
        "size_confound_r": round(size_confound(counts, [per[c]["between"] for c in chs]), 4),
        "most_isolated": max(chs, key=lambda c: per[c]["between"]),
        "kaiwa_share": [round(x, 4) for x in kaiwa_share],
        # PC1 が「文体」ではなく「会話率」を測っていないか(F-19 / T-503 の実演)
        "pc1_vs_kaiwa_share_r": round(
            float(np.corrcoef(np.array(kaiwa_share), coords[:, 0])[0, 1])
            if np.std(kaiwa_share) > 0 else 0.0, 4),
    }
