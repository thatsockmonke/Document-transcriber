"""Offline spelling, project vocabulary, and explicitly learned corrections."""

import math
import re
from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache

from rapidfuzz import process
from rapidfuzz.distance import DamerauLevenshtein
from spellchecker import SpellChecker

from .context import ContextModel

WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)


@dataclass(frozen=True)
class Suggestion:
    word: str
    reason: str
    similarity: int
    score: float
    context_evidence: int = 0


class Dictionary:
    def __init__(self, personal=(), corrections=None, reviewed_texts=()):
        self.speller = SpellChecker(language="en", distance=1)
        self.personal = set(w.casefold() for w in personal)
        self.speller.word_frequency.load_words(self.personal)
        self.learned = dict(corrections or {})
        self._words = sorted(self.speller.word_frequency.words())
        self._known_cache = {}
        self.context = ContextModel(reviewed_texts)

    def known(self, word: str) -> bool:
        normalized = word.casefold().replace("’", "'")
        if len(normalized) < 2:
            return True
        if normalized not in self._known_cache:
            self._known_cache[normalized] = normalized in self.speller
        return self._known_cache[normalized]

    def suggestions(self, word: str) -> list[str]:
        return [suggestion.word for suggestion in self.rank(word)]

    @lru_cache(maxsize=1024)
    def candidates(self, word: str) -> tuple[str, ...]:
        limit = 1 if len(word) < 4 else 2
        matches = process.extract(
            word, self._words, scorer=DamerauLevenshtein.distance, score_cutoff=limit, limit=100
        )
        found = {match[0] for match in matches if match[0] != word}
        if word in self.learned:
            found.add(self.learned[word].casefold())
        confusion_groups = [
            {"their", "there", "they're"},
            {"your", "you're"},
            {"its", "it's"},
            {"to", "too", "two"},
            {"then", "than"},
            {"affect", "effect"},
            {"accept", "except"},
            {"lose", "loose"},
            {"weather", "whether"},
            {"principal", "principle"},
            {"peace", "piece"},
            {"read", "red", "reed"},
            {"right", "write"},
            {"form", "from"},
        ]
        for group in confusion_groups:
            if word in group:
                found.update(group - {word})
        return tuple(sorted(found))

    def rank(
        self, word: str, before: str = "", after: str = "", use_context=True
    ) -> list[Suggestion]:
        word = word.casefold().strip()
        if not WORD_RE.fullmatch(word) or len(word) > 32:
            return []
        ranked = []
        for candidate in self.candidates(word):
            distance = DamerauLevenshtein.distance(word, candidate)
            similarity = round(100 * (1 - distance / max(len(word), len(candidate))))
            score = -2.8 * distance + 0.60 * math.log1p(self.speller.word_frequency[candidate])
            reason = f"{similarity}% spelling similarity"
            evidence = 0
            if use_context and (before or after):
                fit = self.context.fit(candidate, before, after)
                if fit.evidence:
                    score += 0.85 * fit.gain
                    evidence = fit.evidence
                    reason = f"Fits “{fit.phrase}” · {similarity}% similar"
            if candidate in self.personal:
                score += 1
                reason += " · project vocabulary"
            if self.learned.get(word, "").casefold() == candidate:
                score += 0.5 if self.known(word) else 4
                reason = "Your approved replacement · " + reason
            ranked.append(Suggestion(candidate, reason, similarity, score, evidence))
        return sorted(ranked, key=lambda suggestion: (-suggestion.score, suggestion.word))[:7]

    def complete(self, prefix: str) -> list[str]:
        prefix = prefix.casefold()
        if len(prefix) < 2:
            return []
        start = bisect_left(self._words, prefix)
        words = []
        for word in self._words[start : start + 1000]:
            if not word.startswith(prefix):
                break
            words.append(word)
        return sorted(words, key=lambda w: (-self.speller.word_frequency[w], w))[:8]

    def correction(self, word: str) -> str | None:
        # A learned correction between valid words can depend on meaning. Keep
        # those reviewable instead of changing every occurrence while typing.
        if self.known(word):
            return None
        replacement = self.learned.get(word.casefold())
        if replacement and word[:1].isupper():
            replacement = replacement.upper() if word.isupper() else replacement.capitalize()
        return replacement


def shift_tokens(tokens: list[dict], before: str, after: str) -> list[dict]:
    """Retain alignment only for OCR words untouched by an editor change."""
    if before == after:
        return tokens
    prefix = 0
    while prefix < min(len(before), len(after)) and before[prefix] == after[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < min(len(before), len(after)) - prefix
        and before[len(before) - suffix - 1] == after[len(after) - suffix - 1]
    ):
        suffix += 1
    old_end = len(before) - suffix
    delta = len(after) - len(before)
    result = []
    for token in tokens:
        token = dict(token)
        if token["end"] <= prefix:
            result.append(token)
        elif token["start"] >= old_end:
            token["start"] += delta
            token["end"] += delta
            result.append(token)
    return result


def estimate(text: str, reviewed: bool, wpm: int, elapsed: float) -> dict:
    words = len(WORD_RE.findall(text))
    # Remaining time is a planning heuristic, never an OCR accuracy claim.
    return {
        "words": words,
        "minutes": 0 if reviewed else round(words / max(1, wpm), 1),
        "session_minutes": round(elapsed / 60, 1),
    }
