"""Local transcription tools shared by the desktop dialogs and tests."""

from dataclasses import dataclass
from difflib import SequenceMatcher

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .dictionary import WORD_RE

TERMINOLOGY = {
    "General": [],
    "Medical": [
        "tachycardia",
        "bradycardia",
        "hypertension",
        "myocardial",
        "haemoglobin",
        "hemoglobin",
        "contraindication",
        "intravenous",
    ],
    "Legal": [
        "affidavit",
        "deponent",
        "jurisdiction",
        "appellant",
        "plaintiff",
        "defendant",
        "hereinafter",
        "indemnity",
    ],
    "Historical": [
        "manuscript",
        "folio",
        "recto",
        "verso",
        "palaeography",
        "paleography",
        "archival",
        "provenance",
    ],
    "Academic": [
        "methodology",
        "epistemology",
        "hypothesis",
        "bibliography",
        "longitudinal",
        "qualitative",
        "quantitative",
    ],
}


def comparison(a, b):
    left, right = a.split(), b.split()
    return [
        (tag, " ".join(left[i:j]), " ".join(right[k:end]))
        for tag, i, j, k, end in SequenceMatcher(None, left, right).get_opcodes()
        if tag != "equal"
    ]


@dataclass
class PhraseSuggestion:
    start: int
    end: int
    original: str
    replacement: str
    reason: str


def phrase_suggestions(text, dictionary):
    words = list(WORD_RE.finditer(text))
    proposals = []
    for i, word in enumerate(words):
        value = word.group()
        if i + 1 < len(words):
            nxt = words[i + 1]
            if (
                text[word.end() : nxt.start()].isspace()
                and "\n" not in text[word.end() : nxt.start()]
            ):
                merged = value + nxt.group()
                if len(value) > 1 and len(nxt.group()) > 1:
                    if dictionary.known(merged):
                        proposals.append(
                            PhraseSuggestion(
                                word.start(),
                                nxt.end(),
                                text[word.start() : nxt.end()],
                                merged,
                                "Merge split word",
                            )
                        )
        if (
            not dictionary.known(value)
            or value.casefold() in {"alot", "eachother", "aswell", "infront"}
        ) and len(value) > 3:
            candidates = []
            for cut in range(1, len(value)):
                a, b = value[:cut], value[cut:]
                if (len(a) == 1 and a.casefold() not in {"a", "i"}) or (
                    len(b) == 1 and b.casefold() not in {"a", "i"}
                ):
                    continue
                if dictionary.known(a) and dictionary.known(b):
                    fit = dictionary.context.fit(
                        a.casefold(), text[: word.start()], " " + b + text[word.end() :]
                    )
                    candidates.append((fit.gain, a + " " + b))
            if candidates:
                replacement = max(candidates)[1]
                proposals.append(
                    PhraseSuggestion(
                        word.start(), word.end(), value, replacement, "Split merged word"
                    )
                )
    return proposals


def deskew(image):
    small = ImageOps.grayscale(image)
    small.thumbnail((900, 900))
    best = (float("-inf"), 0)
    for angle in np.arange(-8, 8.01, 0.5):
        rotated = small.rotate(float(angle), fillcolor=255)
        ink = np.asarray(rotated) < 160
        score = float(np.var(ink.sum(axis=1)))
        if score > best[0]:
            best = (score, float(angle))
    return image.rotate(
        best[1], resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white"
    ), best[1]


def suppress_bleed(image):
    gray = ImageOps.grayscale(image)
    background = gray.filter(ImageFilter.GaussianBlur(max(10, image.width / 50)))
    normalized = np.clip(
        np.asarray(gray, dtype=float) / (np.asarray(background, dtype=float) + 1) * 255, 0, 255
    )
    return ImageOps.autocontrast(Image.fromarray(normalized.astype("uint8")), cutoff=2).convert(
        "RGB"
    )


def perspective(image, points):
    if len(points) != 4:
        raise ValueError("Choose four corners: top left, top right, bottom right, bottom left.")
    pts = np.asarray(points, dtype=float)
    edges = np.roll(pts, -1, axis=0) - pts
    crosses = [
        edges[i, 0] * edges[(i + 1) % 4, 1] - edges[i, 1] * edges[(i + 1) % 4, 0] for i in range(4)
    ]
    if not (all(c > 0 for c in crosses) or all(c < 0 for c in crosses)):
        raise ValueError("Corners must form a convex document outline in order.")
    if not np.isfinite(pts).all() or any(
        x < 0 or y < 0 or x > image.width or y > image.height for x, y in points
    ):
        raise ValueError("Corners must lie inside the image.")
    # Solve output-to-input projective transform without OpenCV.
    w = max(np.linalg.norm(pts[1] - pts[0]), np.linalg.norm(pts[2] - pts[3]))
    h = max(np.linalg.norm(pts[3] - pts[0]), np.linalg.norm(pts[2] - pts[1]))
    if min(w, h) < 10:
        raise ValueError("Selected document is too small.")
    target = [(0, 0), (w, 0), (w, h), (0, h)]
    matrix = []
    values = []
    for (x, y), (u, v) in zip(target, points):
        matrix.extend([[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]])
        values.extend([u, v])
    try:
        coeff = np.linalg.solve(matrix, values)
    except np.linalg.LinAlgError as error:
        raise ValueError("Corners form an invalid quadrilateral.") from error
    return image.transform(
        (round(w), round(h)),
        Image.Transform.PERSPECTIVE,
        coeff,
        Image.Resampling.BICUBIC,
        fillcolor="white",
    )
