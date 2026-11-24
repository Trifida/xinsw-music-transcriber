# -*- coding: utf-8 -*-
"""SmartKeyAnalyzer: melody-first key and mode analysis.

This module never transposes notes. It ranks 24 major/minor candidates from
pitch-class duration, phrase-ending evidence, long-note emphasis and
leading-tone resolution. Key-signature readability is a late tie-breaker,
not evidence that changes the musical answer.
"""
from __future__ import annotations

from math import sqrt
from typing import Dict, Iterable, List, Optional, Tuple

PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MAJOR_KEY_NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
MINOR_KEY_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]
MAJOR_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
MINOR_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
MAJOR_STEPS = {0, 2, 4, 5, 7, 9, 11}
MINOR_STEPS = {0, 2, 3, 5, 7, 8, 10}


def _corr(a: List[float], b: List[float]) -> float:
    am, bm = sum(a) / 12.0, sum(b) / 12.0
    da, db = [x - am for x in a], [x - bm for x in b]
    den = sqrt(sum(x*x for x in da) * sum(x*x for x in db))
    return sum(x*y for x, y in zip(da, db)) / den if den else 0.0


def _signature_cost(tonic: int, mode: str) -> int:
    # Conventional enharmonic key-signature cost (minimum accidentals).
    # Pitch classes: C, C#, D, D#, E, F, F#, G, G#, A, A#, B.
    major_cost = [0, 5, 2, 3, 4, 1, 6, 1, 4, 3, 2, 5]
    rel_major = (tonic + (3 if mode == "minor" else 0)) % 12
    return major_cost[rel_major]


def analyze_key(notes: Iterable[Dict], tempo: Optional[float] = None,
                top_n: int = 5) -> Dict:
    """Return ranked key candidates and an honest confidence/ambiguity flag.

    Each note requires midi, start_s and end_s. Input order is normalized.
    The function only analyzes; it never changes MIDI pitches.
    """
    seq = sorted((n for n in notes if int(n.get("midi", -1)) >= 0
                  and float(n.get("end_s", 0)) > float(n.get("start_s", 0))),
                 key=lambda n: float(n["start_s"]))
    if not seq:
        return {"key": None, "mode": None, "confidence": 0.0,
                "status": "insufficient-data", "candidates": [], "evidence": []}

    hist = [0.0] * 12
    durations = []
    for n in seq:
        dur = max(0.02, float(n["end_s"]) - float(n["start_s"]))
        pc = int(n["midi"]) % 12
        hist[pc] += dur
        durations.append(dur)
    total = sum(hist)
    profile = [x / total for x in hist]

    # Phrase endings and sustained notes add structural evidence without
    # treating every final note as an unquestionable tonic.
    ending = seq[-1]
    ending_pc = int(ending["midi"]) % 12
    longest = max(durations)
    long_weights = [min(2.0, 0.65 + d / max(longest, 1e-6)) for d in durations]
    sustained = [0.0] * 12
    for n, w in zip(seq, long_weights):
        sustained[int(n["midi"]) % 12] += w * max(0.02, float(n["end_s"]) - float(n["start_s"]))
    stotal = sum(sustained) or 1.0
    sustained = [x / stotal for x in sustained]

    # Detect phrase endings from meaningful gaps. Tempo is only used to scale
    # the silence threshold; no beat/downbeat claims are made from tempo alone.
    beat_s = 60.0 / tempo if tempo and tempo > 0 else 0.5
    phrase_gap_s = max(0.18, 0.35 * beat_s)
    phrase_end_pcs = []
    for idx, note in enumerate(seq):
        is_last = idx == len(seq) - 1
        gap_after = (float(seq[idx + 1]["start_s"]) - float(note["end_s"])) if not is_last else 0.0
        if is_last or gap_after >= phrase_gap_s:
            phrase_end_pcs.append(int(note["midi"]) % 12)
    phrase_end_hist = [phrase_end_pcs.count(pc) / max(1, len(phrase_end_pcs)) for pc in range(12)]

    # Last two notes can reveal leading-tone -> tonic resolution.
    penult_pc = int(seq[-2]["midi"]) % 12 if len(seq) > 1 else None
    candidates = []
    for tonic in range(12):
        for mode, raw_profile, steps in (
            ("major", MAJOR_PROFILE, MAJOR_STEPS),
            ("minor", MINOR_PROFILE, MINOR_STEPS),
        ):
            rotated = [raw_profile[(pc - tonic) % 12] for pc in range(12)]
            tonal_fit = _corr(profile, rotated)
            sustained_fit = _corr(sustained, rotated)
            tonic_share = hist[tonic] / total
            ending_bonus = 0.12 if ending_pc == tonic else 0.0
            if penult_pc is not None:
                leading = (tonic - 1) % 12
                subtonic = (tonic - 2) % 12
                if penult_pc == leading and ending_pc == tonic:
                    ending_bonus += 0.16
                elif mode == "minor" and penult_pc == subtonic and ending_pc == tonic:
                    ending_bonus += 0.10
            # Penalize candidates that explain little of the actual pitch-class
            # duration, but do not label chromatic notes as errors.
            in_scale_share = sum(hist[pc] for pc in range(12)
                                 if (pc - tonic) % 12 in steps) / total
            phrase_end_share = phrase_end_hist[tonic]
            score = (0.50 * tonal_fit + 0.18 * sustained_fit
                     + 0.12 * in_scale_share + 0.08 * min(1.0, tonic_share * 4)
                     + 0.12 * phrase_end_share + ending_bonus)
            candidates.append({
                "key": (MAJOR_KEY_NAMES if mode == "major" else MINOR_KEY_NAMES)[tonic], "mode": mode,
                "label": (MAJOR_KEY_NAMES if mode == "major" else MINOR_KEY_NAMES)[tonic] + ("大调" if mode == "major" else "小调"),
                "score": round(score, 6),
                "signature_cost": _signature_cost(tonic, mode),
                "in_scale_share": round(in_scale_share, 4),
                "phrase_end_share": round(phrase_end_share, 4),
            })

    candidates.sort(key=lambda x: (x["score"], -x["signature_cost"]), reverse=True)
    # Signature complexity can break only a near-tie; it cannot overrule a
    # meaningful musical-score difference.
    top_score = candidates[0]["score"]
    near = [c for c in candidates if top_score - c["score"] <= 0.015]
    chosen = min(near, key=lambda c: (c["signature_cost"], -c["score"]))
    next_score = max((c["score"] for c in candidates if c is not chosen), default=0.0)
    margin = max(0.0, chosen["score"] - next_score)
    confidence = min(1.0, max(0.0, margin / 0.08))
    if len(seq) < 5 or total < 1.0:
        status = "insufficient-data"
    elif margin < 0.012:
        status = "ambiguous"
    else:
        status = "probable"

    evidence = [
        "综合音级时值分布与调性轮廓",
        "对较长音符增加结构权重",
        "参考停顿识别出的乐句结束音及末两音解决关系",
        "调号复杂度只用于近似同分候选的可读性决胜",
    ]
    return {
        "key": chosen["key"], "mode": chosen["mode"], "label": chosen["label"],
        "confidence": round(confidence, 3), "status": status,
        "ending_pitch_class": PITCH_NAMES[ending_pc],
        "phrase_endings": [PITCH_NAMES[pc] for pc in phrase_end_pcs],
        "tempo_used": tempo if tempo and tempo > 0 else None,
        "candidates": [chosen] + [c for c in sorted(candidates, key=lambda c: c["score"], reverse=True) if c is not chosen][:max(0, top_n - 1)],
        "evidence": evidence,
        "transposed": False,
    }
