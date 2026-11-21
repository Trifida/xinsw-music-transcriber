"""Shared lyric tokenization and MusicXML alignment for the original jianpu renderer.

CJK characters are aligned one per pitched note; contiguous Latin words are one
unit. Punctuation attaches to the previous token, and rests/tied continuations
never consume lyric units.
"""
from __future__ import annotations

import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable


OPENING_PUNCTUATION = set("“‘「『【《〈〔（([{'\"")


def _is_punctuation(char: str) -> bool:
    return unicodedata.category(char).startswith("P")


def _is_latin_or_number(char: str) -> bool:
    category = unicodedata.category(char)
    name = unicodedata.name(char, "")
    return category.startswith(("N", "M")) or name.startswith("LATIN ")


def tokenize_lyrics(value: str) -> list[str]:
    """Tokenize Chinese per character and Latin text per contiguous word."""
    tokens: list[str] = []
    prefix = ""
    chars = list(value or "")
    index = 0
    while index < len(chars):
        char = chars[index]
        if char.isspace() or char == "\u3000":
            index += 1
            continue
        if _is_punctuation(char):
            if char in OPENING_PUNCTUATION or not tokens:
                prefix += char
            else:
                tokens[-1] += char
            index += 1
            continue
        if _is_latin_or_number(char):
            word = char
            index += 1
            while index < len(chars):
                nxt = chars[index]
                if _is_latin_or_number(nxt):
                    word += nxt
                    index += 1
                    continue
                if nxt in {"'", "’"} and index + 1 < len(chars) and _is_latin_or_number(chars[index + 1]):
                    word += nxt + chars[index + 1]
                    index += 2
                    continue
                break
            tokens.append(prefix + word)
            prefix = ""
            continue
        tokens.append(prefix + char)
        prefix = ""
        index += 1
    if prefix and tokens:
        tokens[-1] += prefix
    return tokens


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def attach_lyrics_to_musicxml(musicxml_path: str | Path, tokens: Iterable[str]) -> dict:
    """Write lyric tokens onto successive pitched notes in a MusicXML partwise file.

    Notes tied from a previous segment do not consume a token. Existing lyric
    elements are replaced so rerunning the operation is deterministic.
    """
    path = Path(musicxml_path)
    tree = ET.parse(path)
    root = tree.getroot()
    namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    q = (lambda name: f"{{{namespace}}}{name}") if namespace else (lambda name: name)
    ET.register_namespace("", namespace) if namespace else None

    slots: list[ET.Element] = []
    for note in (node for node in root.iter() if _local_name(node) == "note"):
        for child in list(note):
            if _local_name(child) == "lyric":
                note.remove(child)
        has_pitch = any(_local_name(child) == "pitch" for child in note)
        tied_from_previous = any(
            _local_name(child) == "tie" and child.attrib.get("type") == "stop"
            for child in note
        )
        if has_pitch and not tied_from_previous:
            slots.append(note)

    lyric_tokens = [str(token) for token in tokens if str(token)]
    assigned = min(len(lyric_tokens), len(slots))
    for note, token in zip(slots, lyric_tokens[:assigned]):
        lyric = ET.SubElement(note, q("lyric"))
        ET.SubElement(lyric, q("syllabic")).text = "single"
        ET.SubElement(lyric, q("text")).text = token

    tree.write(path, encoding="utf-8", xml_declaration=True)
    return {
        "lyricSlots": len(slots),
        "tokenCount": len(lyric_tokens),
        "assignedCount": assigned,
        "unassignedCount": max(0, len(lyric_tokens) - assigned),
    }
