"""Declarative writing preferences. Rules never execute user-supplied code."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from uuid import uuid4


@dataclass
class WritingRule:
    id: str
    name: str
    kind: str
    enabled: bool = False
    find: str = ""
    replacement: str = ""
    whole_word: bool = True
    case_sensitive: bool = False
    scope: str = "all"
    exceptions: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("Each rule must be an object.")
        rule = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        if (
            not isinstance(rule.name, str)
            or not rule.name.strip()
            or len(rule.name) > 120
            or rule.kind not in TEMPLATES
            or not isinstance(rule.id, str)
            or not rule.id
        ):
            raise ValueError("Invalid rule name, ID, or type.")
        if any(
            type(value) is not bool
            for value in (rule.enabled, rule.whole_word, rule.case_sensitive)
        ):
            raise ValueError("Rule switches must be true or false.")
        if not all(
            isinstance(value, str) and len(value) <= 2000 for value in (rule.find, rule.replacement)
        ):
            raise ValueError("Replacement text is too long or invalid.")
        if rule.kind == "replace" and not rule.find:
            raise ValueError("A replacement rule needs text to find.")
        if (
            rule.scope not in {"all", "dialogue", "outside"}
            or not isinstance(rule.exceptions, str)
            or len(rule.exceptions) > 2000
        ):
            raise ValueError("Invalid rule scope or exceptions.")
        return rule


TEMPLATES = {
    "sentence_case": ("Capitalize sentence beginnings", "hello. goodbye. → Hello. Goodbye."),
    "date_dmy_iso": ("Dates: day/month/year to ISO", "24/10/2026 → 2026-10-24"),
    "date_mdy_iso": ("Dates: month/day/year to ISO", "10/24/2026 → 2026-10-24"),
    "comma_before_quote": ("Comma before opening quotes", 'She said "Hello." → She said, "Hello."'),
    "comma_inside_quote": (
        "Move commas inside closing quotes",
        '"Hello", she said. → "Hello," she said.',
    ),
    "dialogue_comma": (
        "Comma before dialogue attribution",
        '"Hello" she said. → "Hello," she said.',
    ),
    "smart_quotes": ("Use curly double quotes", '"Hello" → “Hello”'),
    "straight_quotes": ("Use straight double quotes", '“Hello” → "Hello"'),
    "single_spaces": (
        "One space between words",
        "Two   spaces → Two spaces (indentation stays intact)",
    ),
    "trim_trailing": (
        "Remove spaces at line endings",
        "Remove trailing spaces; preserve line breaks.",
    ),
    "replace": (
        "Replace a word or phrase",
        "Your own literal replacement, with optional word boundaries.",
    ),
}


def new_rule(kind):
    return WritingRule(uuid4().hex, TEMPLATES[kind][0], kind)


def default_rules():
    # Opt-in writing preferences, not universal grammar requirements.
    return [
        WritingRule(kind, TEMPLATES[kind][0], kind)
        for kind in ("comma_before_quote", "comma_inside_quote", "dialogue_comma", "single_spaces")
    ]


@dataclass(frozen=True)
class Edit:
    start: int
    end: int
    replacement: str


@dataclass
class RulePreview:
    before: str
    after: str
    edits: list[Edit]
    applied_rules: list[str]


QUOTE_RE = re.compile(r'"(?:[^"\\]|\\.)*"|“[^”]*”')


def _quote_edits(text, kind):
    edits = []
    for match in QUOTE_RE.finditer(text):
        start, end = match.span()
        if kind == "comma_before_quote":
            previous = start - 1
            while previous >= 0 and text[previous] in " \t":
                previous -= 1
            if previous >= 0 and (text[previous].isalnum() or text[previous] in ")]'"):
                edits.append(Edit(previous + 1, previous + 1, ","))
        elif kind == "comma_inside_quote":
            if end < len(text) and text[end] == "," and end - start > 2:
                if text[end - 2] not in ".!?;:…":
                    replacement = text[start : end - 1].rstrip(",") + "," + text[end - 1]
                    edits.append(Edit(start, end + 1, replacement))
        elif kind == "dialogue_comma":
            attribution = re.match(
                r"[ \t]+(?:he|she|they|we|I|you|[A-Z][a-z]+)[ \t]+"
                r"(?:said|asked|replied|whispered|shouted|answered|added|wrote)\b",
                text[end:],
            )
            if attribution and end - start > 2 and text[end - 2] not in ",.!?;:…":
                edits.append(Edit(end - 1, end - 1, ","))
        elif kind == "smart_quotes":
            if text[start] == '"':
                edits.extend([Edit(start, start + 1, "“"), Edit(end - 1, end, "”")])
        elif kind == "straight_quotes":
            if text[start] == "“":
                edits.extend([Edit(start, start + 1, '"'), Edit(end - 1, end, '"')])
    return edits


def edits_for_rule(text, rule):
    if rule.kind == "sentence_case":
        return [
            Edit(m.start(1), m.end(1), m.group(1).upper())
            for m in re.finditer(r"(?:^|[.!?]\s+)([a-z])", text)
        ]
    if rule.kind in {"date_dmy_iso", "date_mdy_iso"}:
        from datetime import date

        edits = []
        for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text):
            a, b, y = map(int, m.groups())
            try:
                value = date(y, b, a) if rule.kind == "date_dmy_iso" else date(y, a, b)
            except ValueError:
                continue
            edits.append(Edit(m.start(), m.end(), value.isoformat()))
        return edits
    if rule.kind in {
        "comma_before_quote",
        "comma_inside_quote",
        "dialogue_comma",
        "smart_quotes",
        "straight_quotes",
    }:
        return _quote_edits(text, rule.kind)
    if rule.kind == "single_spaces":
        return [
            Edit(match.start(), match.end(), " ")
            for match in re.finditer(r"(?<=\S)[ \t]{2,}(?=\S)", text)
        ]
    if rule.kind == "trim_trailing":
        return [
            Edit(match.start(), match.end(), "")
            for match in re.finditer(r"[ \t]+$", text, re.MULTILINE)
        ]
    if rule.kind == "replace":
        if not rule.find:
            return []
        pattern = re.escape(rule.find)
        if rule.whole_word:
            pattern = r"(?<!\w)" + pattern + r"(?!\w)"
        flags = 0 if rule.case_sensitive else re.IGNORECASE
        return [
            Edit(match.start(), match.end(), rule.replacement)
            for match in re.finditer(pattern, text, flags)
        ]
    raise ValueError("Unknown rule type")


def validate_rules(data):
    if not isinstance(data, list) or len(data) > 100:
        raise ValueError("A profile must contain at most 100 rules.")
    rules = [WritingRule.from_dict(item) for item in data]
    if len({rule.id for rule in rules}) != len(rules):
        raise ValueError("Rule IDs must be unique.")
    if any(r.enabled and r.kind == "smart_quotes" for r in rules) and any(
        r.enabled and r.kind == "straight_quotes" for r in rules
    ):
        raise ValueError("Choose either curly or straight quotes, not both.")
    return rules


def preview_rules(text: str, rules: list[WritingRule]) -> RulePreview:
    after = text
    applied = []
    for rule in rules:
        if not rule.enabled:
            continue
        edits = edits_for_rule(after, rule)
        quotes = [m.span() for m in QUOTE_RE.finditer(after)]
        exceptions = [s.strip().casefold() for s in rule.exceptions.split(",") if s.strip()]
        filtered = []
        for edit in edits:
            inside = any(a < edit.start < b - 1 for a, b in quotes)
            if rule.scope == "dialogue" and not inside:
                continue
            if rule.scope == "outside" and inside:
                continue
            a = after.rfind("\n", 0, edit.start) + 1
            b = after.find("\n", edit.end)
            line = after[a : b if b >= 0 else len(after)].casefold()
            if any(exception in line for exception in exceptions):
                continue
            filtered.append(edit)
        edits = filtered
        previous = after
        for edit in reversed(edits):
            after = after[: edit.start] + edit.replacement + after[edit.end :]
            if len(after) > min(5_000_000, len(text) * 10 + 100_000):
                raise ValueError(
                    "These rules expand the text too much. Review the replacement rules."
                )
        if after != previous:
            applied.append(rule.name)
    if text == after:
        return RulePreview(text, after, [], applied)
    matcher = SequenceMatcher(None, text, after, autojunk=len(text) > 10_000)
    edits = [Edit(i, j, after[a:b]) for tag, i, j, a, b in matcher.get_opcodes() if tag != "equal"]
    return RulePreview(text, after, edits, applied)
