"""An offline, inspectable context scorer with reviewed-project adaptation."""

from __future__ import annotations

import gzip
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

TOKEN_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)


def tokens(text: str) -> list[str]:
    return [m.group().casefold().replace("’", "'") for m in TOKEN_RE.finditer(text)]


@dataclass(frozen=True)
class ContextFit:
    gain: float = 0
    evidence: int = 0
    phrase: str = ""


@lru_cache(maxsize=1)
def bundled_counts():
    path = Path(__file__).with_name("data") / "context-en.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        data = json.load(stream)
    if data.get("format") != "transcriber-context/1":
        raise ValueError("Unsupported context model format")
    return data


class ContextModel:
    def __init__(self, reviewed_texts=()):
        self.data = bundled_counts()
        self.documents = dict(reviewed_texts)
        self._rebuild()

    def _rebuild(self):
        self.one, self.two, self.three = Counter(), Counter(), Counter()
        remaining = 1_000_000
        for text in self.documents.values():
            # Limit adaptation memory; documents themselves remain unmodified.
            if remaining <= 0:
                break
            excerpt = text[: min(200_000, remaining)]
            remaining -= len(excerpt)
            for sentence in re.split(r"[.!?]+\s+|\n", excerpt):
                words = tokens(sentence)
                self.one.update(words)
                self.two.update("\t".join(p) for p in zip(words, words[1:]))
                self.three.update("\t".join(p) for p in zip(words, words[1:], words[2:]))
        self.total = self.data["total"] + 25 * sum(self.one.values())

    def update(self, page_id: str, text: str, reviewed: bool):
        previous = self.documents.get(page_id)
        if reviewed and previous != text:
            self.documents[page_id] = text
            self._rebuild()
        elif not reviewed and previous is not None:
            del self.documents[page_id]
            self._rebuild()

    def count(self, words):
        key = "\t".join(words)
        name, project = (("unigrams", self.one), ("bigrams", self.two), ("trigrams", self.three))[
            len(words) - 1
        ]
        return self.data[name].get(key, 0) + 25 * project.get(key, 0)

    def probability(self, word, history):
        vocabulary = len(self.data["unigrams"])
        base = (self.count([word]) + 0.5) / (self.total + 0.5 * vocabulary)
        if not history:
            return base
        count = self.count([history[-1], word])
        probability = (count + 5 * base) / (self.count([history[-1]]) + 5) if count else base
        if len(history) >= 2 and self.count([*history[-2:], word]):
            probability = (self.count([*history[-2:], word]) + 3 * probability) / (
                self.count(history[-2:]) + 3
            )
        return probability

    def fit(self, candidate: str, before: str, after: str) -> ContextFit:
        # Sentence and paragraph boundaries limit the usable context.
        left = tokens(re.split(r"[.!?\n]", before)[-1])[-2:]
        right = tokens(re.split(r"[.!?\n]", after)[0])[:2]
        if not left and not right:
            return ContextFit()
        phrase_options = []
        if left:
            phrase_options.append([left[-1], candidate])
        if right:
            phrase_options.append([candidate, right[0]])
        if left and right:
            phrase_options.append([left[-1], candidate, right[0]])
        if len(left) == 2:
            phrase_options.append([*left, candidate])
        if len(right) == 2:
            phrase_options.append([candidate, *right])
        evidence = [(self.count(phrase), phrase) for phrase in phrase_options]
        supported = [(count, phrase) for count, phrase in evidence if count >= 2]
        if not supported:
            return ContextFit()
        # Compare conditional likelihood with the unigram baseline. Right-context
        # terms are normalized too, so common following words cannot dominate.
        gain = math.log(self.probability(candidate, left) / self.probability(candidate, []))
        for index, word in enumerate(right):
            history = [*left, candidate, *right[:index]][-2:]
            baseline = self.probability(word, right[:index])
            gain += 0.8 * math.log(self.probability(word, history) / baseline)
        count, phrase = max(supported, key=lambda item: (len(item[1]), item[0]))
        return ContextFit(max(-8, min(12, gain)), count, " ".join(phrase))
