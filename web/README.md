# Transcribe browser workbench

A static, local-processing version of Document Transcriber for GitHub Pages.
Drag in images, recognize text, and correct the result with a dictionary and
project-style rules. It needs no Python backend, account, or OCR API key.

## Browser workflow

- Drop PNG/JPG/WEBP/BMP/GIF files, choose multiple images, or paste a screenshot.
- Printed OCR uses local Tesseract WebAssembly assets. OCR on import is enabled
  by default; uncheck it to transcribe manually.
- For handwriting, select **Handwriting · TrOCR**, draw a **line / region**, and
  recognize. Quantized model files load into a web worker on the first request.
  They are served by the site; image pixels are not uploaded. The result inserts
  at the editor selection. Single-line recognition is required in this web version.
- Select a word for English spelling alternatives ranked by the bundled local
  context model. All contextual corrections require approval. Only explicitly
  learned misspellings can be auto-corrected, and that option starts disabled.
- Writing rules cover quotation commas, quotation style, spacing, and literal
  whole-word replacements. Preview and approve before applying.
- Notes, text versions, and images persist in IndexedDB. Storage can be denied or
  evicted by browsers; download a workspace backup before clearing site data.
- Export TXT, Markdown, or text/notes JSON. Workspace backup includes original
  images and current transcriptions. Restoring adds documents without replacing
  existing work. Revision history and preferences are browser-local and are not
  included in that backup.

Use a modern desktop browser with WebAssembly, web workers, ImageBitmap,
IndexedDB, and DecompressionStream. Mobile layout is supported, but handwriting
model memory requirements may exceed low-memory devices. Model caching is
browser-managed; this is not a guaranteed offline-installed application.

Images are limited to 20 MB / 32 megapixels and 30 files per import. PDFs, SVG,
multi-engine comparison, persistent queues, writer training exports, perspective
correction, and searchable-PDF export remain desktop features. GIF imports use
the first frame. OCR and statistical context can be wrong; review the result.

## Build and verify

Node 22+ and curl are required. CUDA installation is disabled because this target
uses browser WebAssembly; the unused Node ONNX backend needs no GPU libraries.

```bash
cd web
ONNXRUNTIME_NODE_INSTALL_CUDA=skip npm ci
npm run prepare:assets
npm run lint
npm test
npm run build
npm run test:e2e
```

The Playwright configuration uses system Chromium when available. Otherwise run
`npx playwright install --with-deps chromium` first. Browser tests run actual
Tesseract and quantized TrOCR inference rather than substituting OCR responses.
The default handwriting smoke input is generated cursive text, not an accuracy
benchmark of human handwriting.

`npm run dev` runs the app locally under `/Document-transcriber/`. Set `SITE_BASE`
when building for a different repository path. Runtime OCR assets, dictionary,
WASM modules, and quantized handwriting weights are hosted under that same base.

## Model provenance

The browser handwriting model is
`Xenova/trocr-small-handwritten`, pinned to
`2432e24d184b1d964d07ed04f5d9e21d31a59141`. Asset preparation verifies upstream
SHA256 LFS digests for ONNX weights and Git blob IDs for pinned small files.
Remote model fallback is disabled in the worker. Browser ONNX runs with one thread
so GitHub Pages does not need COOP/COEP headers. English context counts and notices
come from the existing desktop application's bundled public-domain prose model.

Generated heavyweight assets are ignored in the source branch and prepared during
the build. The static deployment includes them. Third-party notices and model
provenance are available from the app's Help dialog.

## GitHub Pages

The workflow at `.github/workflows/pages.yml` builds a verified static artifact
and deploys it through the official GitHub Pages deployment action. In repository
**Settings → Pages**, select **GitHub Actions** as the source, then run the
**Publish browser workbench** workflow. The Pages deployment requires Pages write
and OIDC permissions. Connecting a repository for code access alone may not grant
the connected GitHub app permission to administer Pages settings.

The prepared `gh-pages` branch can also be served through **Deploy from a branch →
gh-pages → /(root)**. That branch contains generated web assets, not the desktop
project or model-training fixtures. Choose one publishing method in Pages settings.

The repository's visibility is preserved. Do not make a private repository public
merely to work around a missing Pages permission or plan setting.
