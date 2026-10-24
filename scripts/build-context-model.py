#!/usr/bin/env python3
"""Rebuild the bundled English n-gram model from pinned public-domain prose."""

import argparse
import gzip
import hashlib
import json
import re
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

REVISION = "550b6625bcef1f2abff2ff770a5a0d272c9c6b2a"
ARCHIVE_SHA256 = "2d3c3ab548c653944310f37f536443ec85d0a0ad855fcae217a0c9efdce2d611"
URL = f"https://raw.githubusercontent.com/nltk/nltk_data/{REVISION}/packages/corpora/gutenberg.zip"
EXCLUDED = ("bible-", "blake-", "milton-", "shakespeare-", "whitman-")
WORDS = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use an already downloaded, verified archive")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "src/document_transcriber/data",
    )
    args = parser.parse_args()
    if args.archive:
        data = args.archive.read_bytes()
    else:
        with urllib.request.urlopen(URL, timeout=60) as response:
            data = response.read()
    if hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("Corpus checksum mismatch; refusing to train from unknown content.")
    import io

    one, two, three = Counter(), Counter(), Counter()
    selected = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        notice = archive.read("gutenberg/README")
        for filename in sorted(archive.namelist()):
            if not filename.endswith(".txt") or Path(filename).name.startswith(EXCLUDED):
                continue
            selected.append(Path(filename).name)
            text = archive.read(filename).decode("utf-8", errors="replace").replace("’", "'")
            for sentence in re.split(r"[.!?]+[\s\"”']+|\n\s*\n", text):
                tokens = [m.group().casefold() for m in WORDS.finditer(sentence)]
                one.update(tokens)
                two.update("\t".join(pair) for pair in zip(tokens, tokens[1:]))
                three.update("\t".join(triple) for triple in zip(tokens, tokens[1:], tokens[2:]))
    payload = {
        "format": "transcriber-context/1",
        "total": sum(one.values()),
        "unigrams": dict(sorted(one.items())),
        "bigrams": dict(sorted((k, v) for k, v in two.items() if v >= 2)),
        "trigrams": dict(sorted((k, v) for k, v in three.items() if v >= 2)),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "context-en.json.gz").open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            compressed.write(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
            )
    (args.output / "GUTENBERG-NOTICE.txt").write_bytes(notice)
    metadata = {
        "name": "English prose context model",
        "format": "transcriber-context/1",
        "source": URL,
        "source_sha256": ARCHIVE_SHA256,
        "documents": selected,
        "tokens": payload["total"],
        "language": "English",
        "model_sha256": hashlib.sha256(
            (args.output / "context-en.json.gz").read_bytes()
        ).hexdigest(),
        "limitations": "Public-domain literary English, not a modern semantic model. "
        "N-gram rankings can be wrong. No automatic contextual replacements.",
    }
    (args.output / "context-model-card.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Built context model: {payload['total']:,} words, {len(two):,} unique bigrams")


if __name__ == "__main__":
    main()
