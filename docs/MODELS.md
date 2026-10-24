# Model provenance and validation

The application never uploads document content for model inference.

## English context model

`src/document_transcriber/data/context-en.json.gz` contains unigram, bigram, and
trigram counts trained on 1,050,014 words of public-domain English prose. The source
is the NLTK Gutenberg selection at revision
`550b6625bcef1f2abff2ff770a5a0d272c9c6b2a`. The exact archive digest, included texts,
and generated-model digest are in `context-model-card.json`; the original notices
are preserved in `GUTENBERG-NOTICE.txt`. Rebuild with `scripts/build-context-model.py`.

This is a small literary-English language model. It can rank spelling neighbours
using nearby phrases, but cannot reliably infer meaning, modern specialist jargon,
or an author's intent. Reviewed project pages adapt its counts locally. Unreviewed
OCR does not teach it. Contextual replacements require approval.

## Handwriting

Model: [microsoft/trocr-small-handwritten](https://huggingface.co/microsoft/trocr-small-handwritten).
Pinned revision: `b4648cfa171985a6745f37ddd637e98c0da958ac`.
62 million parameters; DeiT encoder and TrOCR decoder, fine-tuned on English IAM
handwriting. Model files occupy about 247 MB. The portable ZIP is about 148 MB.

The upstream model card is included in the pack. Its card declares no separate
weight license; the MIT license from the linked Microsoft/unilm repository is
included as an upstream notice, without relabeling the model card. The license
notice was retrieved at unilm revision
`31c5b904ca1bf2afb4c234a6675c683a4e5fc7cd`. This application's bundle does not include
IAM training or test images.

The model weights and SentencePiece tokenizer SHA256 values were checked against
upstream LFS metadata. Configuration/tokenizer files were obtained from that same
immutable revision over verified HTTPS. Expected digests are pinned in `models.py`.
Imports reject extra paths, symlinks, duplicate ZIP entries, unsupported provenance,
oversized archives, and modified payloads. Successful imports replace the model
directory only after verification; failures preserve the previous installation.
Inference uses local files only, disables remote model code, and uses PyTorch's
restricted weights loader through Transformers.

## Validation performed

The full model pack was exported, installed into a separate directory, and all files
were verified with network access disabled. CPU inference was exercised on an
external IAM test line and an upstream OCR test crop. Neither image is distributed
with this application.

On the tested 93-character line, the model produced 9 character edits against the
reference, including a proper-noun error. The cropped word was also misread. These
are smoke tests, not a benchmark or a general accuracy estimate. Real documents
must be reviewed; clean, single-line selections are the supported starting point.
Full-page line segmentation remains experimental. TrOCR has no calibrated word
confidence, so its readings are marked unscored in the review queue.

Reproduce a local line check with `scripts/validate-handwriting.py --model-dir ...
--image ... --reference ...`. The script forces offline model use and reports raw
character edit rate. No recognition assertions are weakened to hide errors.
