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
        if char in {"—", "~", "·"}:
            tokens.append(char)
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




def is_editable_melody_musicxml(musicxml_path: str | Path) -> bool:
    """Return whether a MusicXML file represents one editable monophonic melody.

    Lyric slots are meaningful only for a single melodic line. Reject scores
    with multiple parts, explicit chord notes, or multiple voices/backup
    passages rather than silently assigning syllables to accompaniment notes.
    """
    try:
        root = ET.parse(Path(musicxml_path)).getroot()
    except (OSError, ET.ParseError, TypeError, ValueError):
        return False

    if _local_name(root) != "score-partwise":
        return False
    parts = [node for node in root if _local_name(node) == "part"]
    if len(parts) != 1:
        return False

    voices: set[str] = set()
    pitched_notes = 0
    for node in parts[0].iter():
        name = _local_name(node)
        if name in {"backup", "forward"}:
            return False
        if name == "note":
            if any(_local_name(child) == "chord" for child in node):
                return False
            if any(_local_name(child) == "pitch" for child in node):
                pitched_notes += 1
                voice = next(
                    ((child.text or "").strip()
                     for child in node if _local_name(child) == "voice"),
                    "",
                )
                if voice:
                    voices.add(voice)
    return pitched_notes > 0 and len(voices) <= 1


def read_lyric_slots(musicxml_path: str | Path) -> list[dict]:
    """Return one editable lyric cell for each pitched note that can receive a syllable."""
    root = ET.parse(Path(musicxml_path)).getroot()
    slots: list[dict] = []
    for note in (node for node in root.iter() if _local_name(node) == "note"):
        if not any(_local_name(child) == "pitch" for child in note):
            continue
        if any(
            _local_name(child) == "tie" and child.attrib.get("type") == "stop"
            for child in note
        ):
            continue

        pitch_node = next(child for child in note if _local_name(child) == "pitch")
        step = next((child.text or "" for child in pitch_node if _local_name(child) == "step"), "")
        octave = next((child.text or "" for child in pitch_node if _local_name(child) == "octave"), "")
        alter_text = next((child.text or "0" for child in pitch_node if _local_name(child) == "alter"), "0")
        try:
            alter = int(float(alter_text))
        except (TypeError, ValueError):
            alter = 0
        accidental = "#" if alter > 0 else "b" if alter < 0 else ""
        duration = next((child.text or "" for child in note if _local_name(child) == "duration"), "")
        lyric_node = next((child for child in note if _local_name(child) == "lyric"), None)
        lyric_text = ""
        extend_type = ""
        if lyric_node is not None:
            lyric_text = next(
                (child.text or "" for child in lyric_node if _local_name(child) == "text"), ""
            )
            extend_node = next(
                (child for child in lyric_node if _local_name(child) == "extend"), None
            )
            if extend_node is not None:
                extend_type = extend_node.attrib.get("type", "")
        if not lyric_text and extend_type in {"continue", "stop"}:
            lyric_text = "—"
        slots.append({
            "index": len(slots),
            "pitch": f"{step}{accidental}{octave}",
            "duration": duration,
            "lyric": lyric_text,
            "extend": extend_type,
        })
    return slots

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
    previous_has_text = False
    for index, (note, token) in enumerate(zip(slots, lyric_tokens[:assigned])):
        next_token = lyric_tokens[index + 1] if index + 1 < assigned else None
        if token in {"—", "~"}:
            if not previous_has_text:
                raise ValueError("歌词延续符前面必须先有一个实际歌词音节")
            lyric = ET.SubElement(note, q("lyric"))
            extend_type = "continue" if next_token in {"—", "~"} else "stop"
            ET.SubElement(lyric, q("extend"), {"type": extend_type})
            continue
        if token == "·":
            previous_has_text = False
            continue
        lyric = ET.SubElement(note, q("lyric"))
        ET.SubElement(lyric, q("syllabic")).text = "single"
        ET.SubElement(lyric, q("text")).text = token
        if next_token in {"—", "~"}:
            ET.SubElement(lyric, q("extend"), {"type": "start"})
        previous_has_text = True

    tree.write(path, encoding="utf-8", xml_declaration=True)
    return {
        "lyricSlots": len(slots),
        "tokenCount": len(lyric_tokens),
        "assignedCount": assigned,
        "unassignedCount": max(0, len(lyric_tokens) - assigned),
    }
