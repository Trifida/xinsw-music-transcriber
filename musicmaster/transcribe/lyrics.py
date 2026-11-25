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
        if char in {"—", "–"}:
            tokens.append(prefix + "—")
            prefix = ""
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


def _note_pitch(note: ET.Element) -> str:
    pitch = next((child for child in note if _local_name(child) == "pitch"), None)
    if pitch is None:
        return ""
    step = next((child.text or "" for child in pitch if _local_name(child) == "step"), "")
    alter = next((child.text or "0" for child in pitch if _local_name(child) == "alter"), "0")
    octave = next((child.text or "" for child in pitch if _local_name(child) == "octave"), "")
    accidental = {"1": "#", "-1": "b", "0": ""}.get(alter, f"({alter})")
    return f"{step}{accidental}{octave}"


def _lyric_slots(root: ET.Element) -> list[dict]:
    slots: list[dict] = []
    note_index = 0
    for note in (node for node in root.iter() if _local_name(node) == "note"):
        has_pitch = any(_local_name(child) == "pitch" for child in note)
        tied_from_previous = any(
            _local_name(child) == "tie" and child.attrib.get("type") == "stop"
            for child in note
        )
        if has_pitch and not tied_from_previous:
            lyric = next((child for child in note if _local_name(child) == "lyric"), None)
            text = ""
            if lyric is not None:
                text_node = next((child for child in lyric.iter() if _local_name(child) == "text"), None)
                text = text_node.text or "" if text_node is not None else ""
            slots.append({
                "index": note_index,
                "pitch": _note_pitch(note),
                "lyric": text,
            })
        note_index += 1
    return slots


def extract_lyric_slots(musicxml_path: str | Path) -> list[dict]:
    """Return one editable lyric slot per pitched note (excluding tied continuations)."""
    return _lyric_slots(ET.parse(Path(musicxml_path)).getroot())


def apply_lyric_assignments(musicxml_path: str | Path, assignments: Iterable[str]) -> dict:
    """Replace lyrics by exact note-slot position; empty values clear a slot and '—' is retained."""
    path = Path(musicxml_path)
    tree = ET.parse(path)
    root = tree.getroot()
    namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    q = (lambda name: f"{{{namespace}}}{name}") if namespace else (lambda name: name)
    ET.register_namespace("", namespace) if namespace else None
    values = [str(value or "").strip() for value in assignments]
    notes = [node for node in root.iter() if _local_name(node) == "note"]
    slot_notes = []
    for note in notes:
        has_pitch = any(_local_name(child) == "pitch" for child in note)
        tied_from_previous = any(
            _local_name(child) == "tie" and child.attrib.get("type") == "stop"
            for child in note
        )
        if has_pitch and not tied_from_previous:
            slot_notes.append(note)
    if len(values) != len(slot_notes):
        raise ValueError(f"歌词槽位数量不匹配：需要 {len(slot_notes)} 个，收到 {len(values)} 个。")

    for note, value in zip(slot_notes, values):
        for child in list(note):
            if _local_name(child) == "lyric":
                note.remove(child)
        if value:
            lyric = ET.SubElement(note, q("lyric"))
            ET.SubElement(lyric, q("syllabic")).text = "single"
            ET.SubElement(lyric, q("text")).text = value

    tree.write(path, encoding="utf-8", xml_declaration=True)
    slots = _lyric_slots(root)
    return {
        "lyricSlots": len(slots),
        "assignedCount": sum(1 for item in slots if item["lyric"]),
        "emptyCount": sum(1 for item in slots if not item["lyric"]),
        "assignments": slots,
    }


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
