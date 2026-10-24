import "./style.css";
import nspell from "nspell";
import { createWorker } from "tesseract.js";
import {
  defaultRules,
  applyRules,
  wordCount,
  selectionWord,
  rankSuggestions,
  validateBackup,
  decodeContext,
} from "./logic.js";
import * as storage from "./storage.js";

const $ = (id) => document.getElementById(id);
const base = import.meta.env.BASE_URL;
const state = {
  docs: [],
  current: null,
  settings: {
    personal: [],
    learned: {},
    rules: defaultRules(),
    pace: 40,
    context: true,
    autoCorrect: false,
  },
  db: false,
  spell: null,
  context: null,
  bitmap: null,
  region: null,
  selecting: false,
  zoom: 1,
  fit: true,
  busy: false,
  queue: [],
  printed: null,
  hand: null,
  handReady: false,
  handPending: null,
  suggestions: [],
  selectedSuggestion: null,
  selection: null,
  undo: new Map(),
  saveTimers: new Map(),
  generation: 0,
};
const escape = (text) =>
  String(text).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const current = () => state.docs.find((d) => d.id === state.current);
let toastTimer;
function toast(message, error = false) {
  $("toast").textContent = message;
  $("toast").classList.toggle("error-text", error);
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(
    () => ($("toast").hidden = true),
    error ? 9000 : 4500,
  );
}
function status(message) {
  $("status").textContent = message;
}
function modal(title, html) {
  $("modal-title").textContent = title;
  $("modal-body").innerHTML = html;
  if (!$("modal").open) $("modal").showModal();
}
$("close-modal").onclick = () => $("modal").close();
$("modal").addEventListener("click", (event) => {
  if (event.target === $("modal")) {
    const r = $("modal").getBoundingClientRect();
    if (
      event.clientX < r.left ||
      event.clientX > r.right ||
      event.clientY < r.top ||
      event.clientY > r.bottom
    )
      $("modal").close();
  }
});
function progress(message, value = null) {
  $("progress-label").textContent = message;
  $("progress-value").textContent =
    value == null ? "" : `${Math.round(value * 100)}%`;
  if (value == null) $("progress").removeAttribute("value");
  else $("progress").value = value;
}
function setBusy(busy) {
  state.busy = busy;
  $("progress-panel").hidden = !busy;
  $("cancel").hidden = !busy;
  refreshControls();
  renderLibrary();
}
function refreshControls() {
  const has = !!current();
  for (const id of [
    "recognize",
    "select-region",
    "clear-region",
    "reviewed",
    "editor",
    "notes",
    "undo",
    "find",
    "copy",
    "export",
  ])
    $(id).disabled = !has || state.busy;
  $("engine").disabled = state.busy;
}
function metadata() {
  const doc = current();
  const text = doc?.text || "";
  const count = wordCount(text);
  $("word-count").textContent = `${count} WORDS / ${text.length} CHARS`;
  $("estimate").textContent = !doc
    ? "—"
    : doc.reviewed
      ? "REVIEWED ✓"
      : `~${(count / Math.max(5, state.settings.pace)).toFixed(1)} min`;
}
function renderLibrary() {
  const query = $("library-search").value.toLowerCase();
  $("document-count").textContent = String(state.docs.length).padStart(2, "0");
  const docs = state.docs.filter((d) =>
    (d.title + " " + d.text).toLowerCase().includes(query),
  );
  $("document-list").innerHTML = docs.length
    ? docs
        .map(
          (d) =>
            `<button class="document-item ${d.id === state.current ? "active" : ""}" data-document="${d.id}" role="listitem"><strong>▤ &nbsp;${escape(d.title)}</strong><small><span class="document-state">${d.running ? "RECOGNIZING…" : d.queued ? "QUEUED" : d.reviewed ? "✓ REVIEWED" : d.text ? "READY TO REVIEW" : "READY FOR TEXT"}</span> · ${wordCount(d.text)} words</small></button>`,
        )
        .join("")
    : `<p class="library-empty">${query ? "No documents match your search." : "Your documents will appear here.<br>Drop an image anywhere to begin."}</p>`;
  for (const button of $("document-list").querySelectorAll("[data-document]"))
    button.onclick = () => selectDocument(button.dataset.document);
}
function markSave(label) {
  $("save-state").textContent = label;
}
async function persist(doc) {
  clearTimeout(state.saveTimers.get(doc.id));
  state.saveTimers.delete(doc.id);
  if (!state.db) {
    markSave("MEMORY ONLY");
    return;
  }
  try {
    await storage.saveDocument({ ...doc, running: false, queued: false });
    if (doc.id === state.current) markSave("SAVED IN THIS BROWSER");
  } catch (error) {
    markSave("SAVE FAILED");
    toast(
      "Local save failed. Export your text or back up the workspace before closing. " +
        error.message,
      true,
    );
  }
}
function scheduleSave(doc) {
  markSave("UNSAVED CHANGES");
  clearTimeout(state.saveTimers.get(doc.id));
  state.saveTimers.set(
    doc.id,
    setTimeout(() => {
      revision(doc, "manual");
      persist(doc);
      if (doc.id === state.current) renderHistory();
    }, 600),
  );
}
async function savePreferences() {
  try {
    if (state.db) await storage.saveSettings(state.settings);
  } catch (error) {
    toast("Could not save preferences: " + error.message, true);
  }
}
function revision(doc, source) {
  const last = doc.history?.at(-1);
  doc.history ||= [];
  if (last?.text !== doc.text) {
    doc.history.push({
      text: doc.text,
      source,
      time: new Date().toISOString(),
    });
    doc.history = doc.history.slice(-80);
  }
}
function pushUndo(doc) {
  const items = state.undo.get(doc.id) || [];
  if (items.at(-1) !== doc.text) {
    items.push(doc.text);
    state.undo.set(doc.id, items.slice(-80));
  }
}
function setText(doc, text, source = "manual") {
  pushUndo(doc);
  revision(doc, "before " + source);
  doc.text = text;
  doc.reviewed = false;
  revision(doc, source);
  if (doc.id === state.current) {
    $("editor").value = text;
    $("reviewed").checked = false;
    metadata();
    renderHistory();
  }
  persist(doc);
  renderLibrary();
}
async function selectDocument(id) {
  const old = current();
  if (old) {
    revision(old, "manual");
    await persist(old);
  }
  const doc = state.docs.find((d) => d.id === id);
  if (!doc) return;
  state.current = id;
  state.region = null;
  state.selecting = false;
  state.fit = true;
  $("select-region").setAttribute("aria-pressed", "false");
  $("image-canvas").classList.remove("selecting");
  $("region-badge").textContent = "FULL IMAGE";
  $("document-title").textContent = doc.title;
  $("document-description").textContent =
    `${doc.engine || "Ready for transcription"} · ${doc.width} × ${doc.height} pixels`;
  $("image-info").textContent = `${doc.width} × ${doc.height} PX`;
  $("editor").value = doc.text;
  $("notes").value = doc.notes || "";
  $("reviewed").checked = doc.reviewed;
  $("empty-state").hidden = true;
  $("image-container").hidden = false;
  const requested = id;
  try {
    const bitmap = await createImageBitmap(doc.image);
    if (state.current !== requested) {
      bitmap.close();
      return;
    }
    state.bitmap?.close();
    state.bitmap = bitmap;
    drawImage();
  } catch (error) {
    toast("Could not display this image: " + error.message, true);
  }
  markSave(state.db ? "SAVED IN THIS BROWSER" : "MEMORY ONLY");
  metadata();
  renderHistory();
  renderLibrary();
  refreshControls();
}
function drawImage() {
  const canvas = $("image-canvas"),
    bitmap = state.bitmap;
  if (!bitmap) return;
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(bitmap, 0, 0);
  if (state.region) {
    const { x, y, w, h } = state.region;
    ctx.fillStyle = "#f28b422b";
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = "#ed853e";
    ctx.lineWidth = Math.max(2, bitmap.width / 500);
    ctx.setLineDash([ctx.lineWidth * 4, ctx.lineWidth * 3]);
    ctx.strokeRect(x, y, w, h);
  }
  if (state.fit) {
    const stage = $("image-stage");
    state.zoom = Math.min(
      (stage.clientWidth - 44) / bitmap.width,
      (Math.max(400, stage.clientHeight) - 44) / bitmap.height,
      1,
    );
  }
  state.zoom = Math.max(0.03, Math.min(5, state.zoom));
  canvas.style.width = `${bitmap.width * state.zoom}px`;
  canvas.style.height = `${bitmap.height * state.zoom}px`;
  $("zoom-value").textContent = `${Math.round(state.zoom * 100)}%`;
}
new ResizeObserver(() => {
  if (state.fit) drawImage();
}).observe($("image-stage"));
$("zoom-in").onclick = () => {
  state.fit = false;
  state.zoom *= 1.2;
  drawImage();
};
$("zoom-out").onclick = () => {
  state.fit = false;
  state.zoom /= 1.2;
  drawImage();
};
$("fit").onclick = () => {
  state.fit = true;
  drawImage();
};
$("select-region").onclick = () => {
  state.selecting = !state.selecting;
  $("select-region").setAttribute("aria-pressed", String(state.selecting));
  $("image-canvas").classList.toggle("selecting", state.selecting);
  if (state.selecting)
    status(
      "Drag a rectangle around one line. Handwriting recognition works best on a single line.",
    );
};
$("clear-region").onclick = () => {
  state.region = null;
  $("region-badge").textContent = "FULL IMAGE";
  drawImage();
};
let anchor;
function imagePoint(event) {
  const rect = $("image-canvas").getBoundingClientRect();
  return {
    x: Math.max(
      0,
      Math.min(
        state.bitmap.width,
        ((event.clientX - rect.left) * state.bitmap.width) / rect.width,
      ),
    ),
    y: Math.max(
      0,
      Math.min(
        state.bitmap.height,
        ((event.clientY - rect.top) * state.bitmap.height) / rect.height,
      ),
    ),
  };
}
$("image-canvas").onpointerdown = (event) => {
  if (!state.selecting || state.busy || !state.bitmap) return;
  anchor = imagePoint(event);
  $("image-canvas").setPointerCapture(event.pointerId);
};
$("image-canvas").onpointermove = (event) => {
  if (!anchor) return;
  const p = imagePoint(event);
  state.region = {
    x: Math.round(Math.min(anchor.x, p.x)),
    y: Math.round(Math.min(anchor.y, p.y)),
    w: Math.round(Math.abs(anchor.x - p.x)),
    h: Math.round(Math.abs(anchor.y - p.y)),
  };
  drawImage();
};
$("image-canvas").onpointerup = () => {
  if (!anchor) return;
  anchor = null;
  if (state.region?.w < 8 || state.region?.h < 8) state.region = null;
  $("region-badge").textContent = state.region
    ? "REGION → INSERT"
    : "FULL IMAGE";
  drawImage();
  status(
    state.region
      ? "Region selected. OCR inserts text at the editor cursor or replaces its selection."
      : "Selection was too small. Drag around a readable line.",
  );
};
$("image-canvas").onpointercancel = () => {
  anchor = null;
  state.region = null;
  drawImage();
};

async function importImages(files) {
  const images = [...files];
  if (images.length > 30) {
    toast("Import up to 30 images at a time.", true);
    return;
  }
  const added = [];
  for (const file of images) {
    try {
      if (
        (file.type &&
          !/^image\/(png|jpeg|webp|bmp|gif|x-ms-bmp)$/i.test(file.type)) ||
        (!file.type && !/[.](png|jpe?g|webp|bmp|gif)$/i.test(file.name))
      )
        throw new Error(
          "Choose a PNG, JPG, WEBP, BMP, or GIF image. PDFs and SVG files are not supported.",
        );
      if (file.size > 20 * 1024 * 1024)
        throw new Error("The image exceeds the 20 MB limit.");
      const bitmap = await createImageBitmap(file);
      const { width, height } = bitmap;
      bitmap.close();
      if (width * height > 32_000_000 || !width || !height)
        throw new Error("Use an image under 32 megapixels.");
      const doc = {
        id: crypto.randomUUID(),
        title: file.name || "Clipboard image",
        image: file,
        width,
        height,
        text: "",
        notes: "",
        reviewed: false,
        engine: "",
        created: Date.now(),
        history: [],
      };
      state.docs.push(doc);
      added.push(doc);
      await persist(doc);
    } catch (error) {
      toast(`${file.name || "Image"}: ${error.message}`, true);
    }
  }
  if (added.length) {
    await selectDocument(added[0].id);
    status(`Added ${added.length} image(s). Originals stay on this device.`);
    if ($("auto-recognize").checked && $("engine").value === "printed") {
      for (const doc of added) {
        doc.queued = true;
        state.queue.push({ doc, engine: "printed", region: null });
      }
      pumpQueue();
    }
  }
  renderLibrary();
}
function chooseImages() {
  $("file-input").click();
}
for (const id of ["add-images", "browse"]) $(id).onclick = chooseImages;
$("file-input").onchange = (event) => {
  importImages(event.target.files);
  event.target.value = "";
};
let dragDepth = 0;
window.addEventListener("dragenter", (event) => {
  if (event.dataTransfer?.types.includes("Files")) {
    event.preventDefault();
    dragDepth++;
    $("drop-overlay").hidden = false;
  }
});
window.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) $("drop-overlay").hidden = true;
});
window.addEventListener("dragover", (event) => {
  if (event.dataTransfer?.types.includes("Files")) event.preventDefault();
});
window.addEventListener("drop", (event) => {
  event.preventDefault();
  dragDepth = 0;
  $("drop-overlay").hidden = true;
  if (event.dataTransfer?.files.length) importImages(event.dataTransfer.files);
});
window.addEventListener("paste", (event) => {
  if (event.clipboardData?.files.length) {
    event.preventDefault();
    importImages(event.clipboardData.files);
  }
});
$("library-search").oninput = renderLibrary;
async function printedWorker() {
  if (state.printed) return state.printed;
  const generation = state.generation;
  const worker = await createWorker("eng", 1, {
    workerPath: new URL(
      base + "vendor/tesseract/worker.min.js",
      location.origin,
    ).href,
    corePath: new URL(base + "vendor/tesseract-core/", location.origin).href,
    langPath: new URL(base + "vendor/lang/", location.origin).href,
    workerBlobURL: false,
    logger: (message) => {
      if (state.busy)
        progress(
          message.status || "Recognizing locally…",
          message.progress ?? null,
        );
    },
  });
  if (generation !== state.generation) {
    await worker.terminate();
    throw new Error("Cancelled");
  }
  state.printed = worker;
  return worker;
}
function ensureHandWorker() {
  if (state.hand) return;
  state.hand = new Worker(new URL("./handwriting-worker.js", import.meta.url), {
    type: "module",
  });
  state.hand.onmessage = ({ data }) => {
    if (data.type === "progress") progress(data.message, data.progress);
    else if (data.type === "ready") {
      state.handReady = true;
      state.handPending?.resolve();
      state.handPending = null;
    } else if (data.type === "result") {
      state.handReady = true;
      state.handPending?.resolve(data.text);
      state.handPending = null;
    } else if (data.type === "error") {
      state.handPending?.reject(new Error(data.message));
      state.handPending = null;
    }
  };
  state.hand.onerror = (event) => {
    state.handPending?.reject(
      new Error(event.message || "Handwriting worker failed."),
    );
    state.handPending = null;
  };
}
async function handRequest(data) {
  ensureHandWorker();
  return new Promise((resolve, reject) => {
    state.handPending = { resolve, reject };
    state.hand.postMessage(data);
  });
}
async function imageForOcr(doc, region) {
  const bitmap = await createImageBitmap(doc.image);
  const crop = region || { x: 0, y: 0, w: bitmap.width, h: bitmap.height };
  const factor = Math.min(1, 3000 / Math.max(crop.w, crop.h));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(crop.w * factor));
  canvas.height = Math.max(1, Math.round(crop.h * factor));
  canvas
    .getContext("2d")
    .drawImage(
      bitmap,
      crop.x,
      crop.y,
      crop.w,
      crop.h,
      0,
      0,
      canvas.width,
      canvas.height,
    );
  bitmap.close();
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) =>
        blob
          ? resolve(blob)
          : reject(new Error("Could not prepare the image.")),
      "image/png",
    ),
  );
}
async function pumpQueue() {
  if (state.busy || !state.queue.length) return;
  const job = state.queue.shift(),
    { doc, engine, region } = job;
  doc.queued = false;
  doc.running = true;
  setBusy(true);
  const generation = state.generation;
  try {
    progress(`Preparing ${doc.title}…`);
    const image = await imageForOcr(doc, region);
    let text;
    if (engine === "printed") {
      const worker = await printedWorker();
      const result = await worker.recognize(image);
      text = result.data.text.trim();
    } else {
      if (!region)
        throw new Error(
          "For handwriting, use SELECT LINE / REGION and drag around one line first.",
        );
      text = await handRequest({ type: "recognize", image });
    }
    if (generation !== state.generation) return;
    if (!text) {
      toast(
        "No text detected. Try a larger, clearer region or type the transcription manually.",
      );
      return;
    }
    const before = doc.text;
    if (region) {
      const start = job.start ?? before.length,
        end = job.end ?? start;
      setText(
        doc,
        before.slice(0, start) + text + before.slice(end),
        `${engine} OCR · region`,
      );
    } else setText(doc, text, `${engine} OCR`);
    doc.engine =
      engine === "printed"
        ? "Tesseract · printed text"
        : "TrOCR · handwriting (unscored)";
    await persist(doc);
    if (current()?.id === doc.id)
      $("document-description").textContent =
        `${doc.engine} · ${doc.width} × ${doc.height} pixels`;
    status(
      `Recognized ${wordCount(text)} words locally. Review the transcription before exporting.`,
    );
  } catch (error) {
    if (generation === state.generation) {
      toast(
        "Recognition failed. Existing text was preserved. " + error.message,
        true,
      );
      status(
        "Recognition needs attention. You can continue transcribing manually.",
      );
    }
  } finally {
    doc.running = false;
    if (generation === state.generation) {
      setBusy(false);
      pumpQueue();
    }
  }
}
function confirmHandwriting() {
  return (
    state.handReady ||
    confirm(
      "The first handwriting recognition loads a large local model into this browser. Model files are served by this site; your image stays on your device. Continue?",
    )
  );
}
$("recognize").onclick = () => {
  const doc = current();
  if (!doc || state.busy) return;
  const engine = $("engine").value,
    region = state.region ? { ...state.region } : null;
  if (engine === "handwriting" && !region) {
    toast("Select one handwritten line in the image first, then recognize it.");
    if (!state.selecting) $("select-region").click();
    return;
  }
  if (engine === "handwriting" && !confirmHandwriting()) return;
  if (
    !region &&
    doc.text.trim() &&
    !confirm(
      "Replace this image’s transcription with a new OCR reading? Your current text remains in history.",
    )
  )
    return;
  const start = $("editor").selectionStart,
    end = $("editor").selectionEnd;
  state.queue.push({ doc, engine, region, start, end });
  pumpQueue();
};
$("cancel").onclick = async () => {
  state.generation++;
  state.queue.forEach((j) => (j.doc.queued = false));
  state.queue = [];
  state.docs.forEach((d) => (d.running = false));
  const printed = state.printed;
  state.printed = null;
  if (printed) printed.terminate().catch(() => {});
  if (state.hand) {
    state.hand.terminate();
    state.hand = null;
  }
  state.handReady = false;
  state.handPending?.reject(new Error("Cancelled"));
  state.handPending = null;
  setBusy(false);
  status("Recognition stopped. Existing text is preserved.");
};
$("engine").onchange = () => {
  if ($("engine").value === "handwriting")
    toast(
      "Handwriting works best on a single line. Use SELECT LINE / REGION, then recognize.",
    );
};

$("editor").onbeforeinput = () => {
  const doc = current();
  if (doc) pushUndo(doc);
};
$("editor").oninput = () => {
  const doc = current();
  if (!doc) return;
  doc.text = $("editor").value;
  doc.reviewed = false;
  $("reviewed").checked = false;
  metadata();
  scheduleSave(doc);
};
$("editor").addEventListener("keydown", (event) => {
  if (
    state.settings.autoCorrect &&
    [" ", ".", ",", "!", "?", "Enter"].includes(event.key) &&
    state.spell
  ) {
    const input = $("editor");
    if (input.selectionStart !== input.selectionEnd) return;
    const pos = input.selectionStart;
    const prefix = input.value.slice(0, pos);
    const match = /[\p{L}]+(?:['’][\p{L}]+)*$/u.exec(prefix);
    if (match) {
      const original = match[0],
        replacement = state.settings.learned[original.toLowerCase()];
      if (replacement && !state.spell.correct(original.toLowerCase())) {
        input.setRangeText(
          original[0] === original[0].toUpperCase()
            ? replacement[0].toUpperCase() + replacement.slice(1)
            : replacement,
          pos - original.length,
          pos,
          "end",
        );
      }
    }
  }
  if (event.key === "Escape") {
    $("find-bar").hidden = true;
  }
});
$("undo").onclick = () => {
  const doc = current(),
    items = doc && state.undo.get(doc.id);
  if (!items?.length) return;
  const text = items.pop();
  revision(doc, "before undo");
  doc.text = text;
  doc.reviewed = false;
  revision(doc, "undo");
  $("editor").value = text;
  persist(doc);
  metadata();
  renderHistory();
  renderLibrary();
};
$("notes").oninput = () => {
  const doc = current();
  if (doc) {
    doc.notes = $("notes").value;
    scheduleSave(doc);
  }
};
$("reviewed").onchange = () => {
  const doc = current();
  if (doc) {
    doc.reviewed = $("reviewed").checked;
    persist(doc);
    metadata();
    renderLibrary();
  }
};
$("review-pace").onchange = () => {
  state.settings.pace = Math.max(
    5,
    Math.min(300, Number($("review-pace").value) || 40),
  );
  $("review-pace").value = state.settings.pace;
  savePreferences();
  metadata();
};
$("copy").onclick = async () => {
  try {
    await navigator.clipboard.writeText($("editor").value);
    toast("Transcription copied.");
  } catch {
    toast(
      "Clipboard access was denied. Select and copy the text manually.",
      true,
    );
  }
};
$("find").onclick = () => {
  $("find-bar").hidden = false;
  $("find-query").focus();
};
$("close-find").onclick = () => ($("find-bar").hidden = true);
function findNext() {
  const text = $("editor").value,
    query = $("find-query").value;
  if (!query) return;
  let index = text
    .toLowerCase()
    .indexOf(query.toLowerCase(), $("editor").selectionEnd);
  if (index < 0) index = text.toLowerCase().indexOf(query.toLowerCase());
  if (index < 0) {
    toast("No matches in this transcription.");
    return;
  }
  $("editor").focus();
  $("editor").setSelectionRange(index, index + query.length);
}
$("find-next").onclick = findNext;
$("find-query").onkeydown = (e) => {
  if (e.key === "Enter") findNext();
};
window.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "o") {
    event.preventDefault();
    chooseImages();
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    if (current()) persist(current());
  }
  if (
    (event.ctrlKey || event.metaKey) &&
    event.key.toLowerCase() === "f" &&
    document.activeElement === $("editor")
  ) {
    event.preventDefault();
    $("find").click();
  }
});

async function loadDictionary() {
  try {
    const responses = await Promise.all(
      [
        "dictionary/index.aff",
        "dictionary/index.dic",
        "context-en.json.gz",
      ].map((file) => fetch(base + file)),
    );
    if (responses.some((r) => !r.ok))
      throw new Error("Dictionary files could not be loaded.");
    const [aff, dic] = await Promise.all([
      responses[0].text(),
      responses[1].text(),
    ]);
    state.spell = nspell(aff, dic);
    state.settings.personal.forEach((w) => state.spell.add(w));
    state.context = await decodeContext(await responses[2].arrayBuffer());
    $("dictionary-state").textContent = "ENGLISH / LOCAL CONTEXT MODEL";
    renderPersonal();
  } catch (error) {
    $("dictionary-state").textContent = "DICTIONARY UNAVAILABLE";
    toast(error.message + " Manual transcription still works.", true);
  }
}
let lookupTimer;
function editorSelection() {
  if (!current()) return;
  state.selection = selectionWord(
    $("editor").value,
    $("editor").selectionStart,
    $("editor").selectionEnd,
  );
  if (/^[\p{L}]+(?:['’][\p{L}]+)*$/u.test(state.selection.word)) {
    $("lookup").value = state.selection.word;
    clearTimeout(lookupTimer);
    lookupTimer = setTimeout(lookup, 150);
  }
}
for (const event of ["mouseup", "keyup", "select"])
  $("editor").addEventListener(event, editorSelection);
$("lookup-form").onsubmit = (event) => {
  event.preventDefault();
  lookup();
};
function lookup() {
  const word = $("lookup").value.trim();
  state.selectedSuggestion = null;
  $("apply-suggestion").disabled = true;
  if (
    !state.spell ||
    !word ||
    word.length > 32 ||
    !/^[\p{L}]+(?:['’][\p{L}]+)*$/u.test(word)
  )
    return;
  const selected =
    state.selection?.word.toLowerCase() === word.toLowerCase()
      ? state.selection
      : null;
  const text = current()?.text || "";
  let before = "",
    after = "";
  if (selected) {
    before = text.slice(0, selected.start);
    after = text.slice(selected.end);
    const left = before.split("\n").at(-1).slice(-40),
      right = after.split("\n")[0].slice(0, 40);
    $("sentence-context").textContent = `${left}[${word}]${right}`;
  } else
    $("sentence-context").textContent =
      "Standalone lookup · select a word in the editor to use its sentence.";
  const candidates = state.spell.suggest(word.toLowerCase());
  const groups = [
    ["peace", "piece"],
    ["form", "from"],
    ["reed", "read", "red"],
    ["their", "there", "they're"],
    ["your", "you're"],
    ["its", "it's"],
    ["to", "too", "two"],
    ["then", "than"],
    ["lose", "loose"],
  ];
  for (const group of groups)
    if (group.includes(word.toLowerCase())) candidates.push(...group);
  state.suggestions = rankSuggestions(
    word,
    candidates,
    before,
    after,
    state.context,
    state.settings.learned,
    state.settings.context,
  );
  $("dictionary-state").textContent = state.spell.correct(word)
    ? "KNOWN WORD · SIMILAR OPTIONS"
    : "SPELLING NOT RECOGNIZED";
  $("suggestions").innerHTML = state.suggestions.length
    ? state.suggestions
        .map(
          (s, i) =>
            `<button class="suggestion ${s.evidence ? "contextual" : ""}" data-suggestion="${i}">${escape(s.word)}</button>`,
        )
        .join("")
    : '<p class="muted">No close alternatives found. Keep the word or add it to your vocabulary.</p>';
  for (const b of $("suggestions").querySelectorAll("[data-suggestion]"))
    b.onclick = () => chooseSuggestion(Number(b.dataset.suggestion));
  if (state.suggestions.length) chooseSuggestion(0);
}
function chooseSuggestion(index) {
  state.selectedSuggestion = state.suggestions[index];
  $("suggestion-reason").textContent = state.selectedSuggestion.reason;
  $("apply-suggestion").disabled = !state.selection || !current() || state.busy;
  for (const b of $("suggestions").querySelectorAll("button"))
    b.classList.toggle("selected", Number(b.dataset.suggestion) === index);
}
$("apply-suggestion").onclick = () => {
  const doc = current(),
    selection = state.selection,
    suggestion = state.selectedSuggestion;
  if (!doc || !selection || !suggestion || state.busy) return;
  if (doc.text.slice(selection.start, selection.end) !== selection.word) {
    toast("Select the word again; the transcription changed.");
    return;
  }
  let replacement = suggestion.word;
  if (selection.word === selection.word.toUpperCase())
    replacement = replacement.toUpperCase();
  else if (selection.word[0] === selection.word[0].toUpperCase())
    replacement = replacement[0].toUpperCase() + replacement.slice(1);
  if ($("learn-corrections").checked) {
    state.settings.learned[selection.word.toLowerCase()] = suggestion.word;
    savePreferences();
  }
  setText(
    doc,
    doc.text.slice(0, selection.start) +
      replacement +
      doc.text.slice(selection.end),
    "dictionary",
  );
  $("editor").focus();
  $("editor").setSelectionRange(
    selection.start,
    selection.start + replacement.length,
  );
  editorSelection();
};
function renderPersonal() {
  $("personal-words").innerHTML = state.settings.personal
    .map((w) => `<option>${escape(w)}</option>`)
    .join("");
}
$("add-word").onclick = () => {
  const word = $("lookup").value.trim();
  if (!state.spell || !word || !/^[\p{L}]+(?:['’][\p{L}]+)*$/u.test(word)) {
    toast("Enter a single word first.");
    return;
  }
  if (!state.settings.personal.includes(word))
    state.settings.personal.push(word);
  state.spell.add(word);
  savePreferences();
  renderPersonal();
  lookup();
  toast("Added to your local vocabulary.");
};
$("remove-word").onclick = () => {
  const word = $("personal-words").value;
  if (!word) return;
  state.settings.personal = state.settings.personal.filter((w) => w !== word);
  state.spell.remove(word);
  savePreferences();
  renderPersonal();
  lookup();
};
$("use-context").onchange = () => {
  state.settings.context = $("use-context").checked;
  savePreferences();
  lookup();
};
$("auto-correct").onchange = () => {
  state.settings.autoCorrect = $("auto-correct").checked;
  savePreferences();
};
for (const button of document.querySelectorAll("[data-tab]"))
  button.onclick = () => {
    for (const b of document.querySelectorAll("[data-tab]"))
      b.setAttribute("aria-selected", String(b === button));
    for (const name of ["dictionary", "notes", "history"])
      $("tab-" + name).hidden = name !== button.dataset.tab;
  };
function renderHistory() {
  const doc = current();
  $("history-list").innerHTML = doc?.history?.length
    ? [...doc.history]
        .reverse()
        .map(
          (entry, i) =>
            `<div class="history-entry"><small>${escape(new Date(entry.time).toLocaleString())} · ${escape(entry.source)}</small><pre>${escape(entry.text.slice(0, 300) || "(empty transcription)")}</pre><button data-history="${doc.history.length - 1 - i}">RESTORE VERSION</button></div>`,
        )
        .join("")
    : '<p class="muted">Versions appear after text changes are saved.</p>';
  for (const b of $("history-list").querySelectorAll("[data-history]"))
    b.onclick = () => {
      if (state.busy) return;
      const version = doc.history[Number(b.dataset.history)];
      if (
        version &&
        confirm(
          "Restore this version? Your current text will remain in history.",
        )
      )
        setText(doc, version.text, "restore");
    };
}
function download(data, name, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("export").onclick = () => {
  const doc = current();
  if (!doc) return;
  modal(
    "Export transcription",
    `<p>Download your text. The original image remains in this browser; use Back up workspace to include images.</p><div class="actions"><button id="export-txt" class="primary">PLAIN TEXT</button><button id="export-md">MARKDOWN</button><button id="export-json">TEXT + NOTES JSON</button></div><div class="actions"><button id="rename-doc" class="quiet">RENAME IMAGE</button><button id="delete-doc" class="danger">DELETE IMAGE</button></div>`,
  );
  const stem = doc.title.replace(/\.[^.]+$/, "").replace(/[<>:"/\\|?*]/g, "_");
  $("export-txt").onclick = () => download(doc.text, stem + ".txt");
  $("export-md").onclick = () =>
    download(`# ${doc.title}\n\n${doc.text}\n`, stem + ".md");
  $("export-json").onclick = () =>
    download(
      JSON.stringify(
        {
          title: doc.title,
          text: doc.text,
          notes: doc.notes,
          reviewed: doc.reviewed,
          engine: doc.engine,
        },
        null,
        2,
      ),
      stem + ".json",
      "application/json",
    );
  $("rename-doc").onclick = () => {
    const value = prompt("Image title:", doc.title);
    if (value?.trim()) {
      doc.title = value.trim().slice(0, 200);
      persist(doc);
      $("document-title").textContent = doc.title;
      renderLibrary();
      $("modal").close();
    }
  };
  $("delete-doc").onclick = async () => {
    if (
      !confirm(
        "Delete this image and its transcription from this browser? Export or back up anything you want to keep.",
      )
    )
      return;
    clearTimeout(state.saveTimers.get(doc.id));
    if (state.db) await storage.deleteDocument(doc.id);
    state.docs = state.docs.filter((d) => d.id !== doc.id);
    state.current = null;
    $("modal").close();
    if (state.docs.length) await selectDocument(state.docs[0].id);
    else {
      state.bitmap?.close();
      state.bitmap = null;
      $("image-container").hidden = true;
      $("empty-state").hidden = false;
      $("editor").value = "";
      $("notes").value = "";
      $("document-title").textContent = "Make every word readable.";
      $("document-description").textContent =
        "Drop in a scan. Recognize the text. Make it yours.";
      $("image-info").textContent = "NO IMAGE SELECTED";
      refreshControls();
      metadata();
      renderHistory();
      renderLibrary();
    }
  };
};
function rulesDialog() {
  const rules = state.settings.rules;
  modal(
    "Writing rules & style",
    `<p>Choose your preferences, test them, then review the result. Saving rules does not rewrite your transcription.</p>${[
      [
        "commaBefore",
        "Comma before opening quotes",
        "She said “Hello.” → She said, “Hello.”",
      ],
      [
        "commaInside",
        "Move commas inside closing quotes",
        "“Hello”, she said. → “Hello,” she said.",
      ],
      [
        "dialogueComma",
        "Comma before dialogue attribution",
        "“Hello” she said. → “Hello,” she said.",
      ],
      ["smartQuotes", "Use curly double quotes", '"Hello" → “Hello”'],
      [
        "singleSpaces",
        "One space between words",
        "Repeated internal spaces become one; indentation stays.",
      ],
    ]
      .map(
        ([key, title, example]) =>
          `<label class="check"><input type="checkbox" data-rule="${key}" ${rules[key] ? "checked" : ""}>${title}<span class="muted small" style="display:block;margin:5px 0 0 21px">${escape(example)}</span></label>`,
      )
      .join(
        "",
      )}<h3>LITERAL REPLACEMENTS</h3><p class="muted">One per line: abbreviation = expansion. Replacements match whole words, ignoring case.</p><textarea id="custom-rules" aria-label="Literal replacement rules">${escape((rules.replacements || []).map((p) => p.find + " = " + p.replace).join("\n"))}</textarea><h3>LIVE SANDBOX</h3><textarea id="rule-sandbox" aria-label="Rule test text">${escape('She said "Hello" she said.\n"A word", followed by a comma.\nTwo   spaces between words.')}</textarea><pre id="rule-preview"></pre><p id="rule-error" class="error-text"></p><div class="actions"><button id="save-rules">SAVE PREFERENCES</button><button id="apply-rules" class="primary" ${!current() || state.busy ? "disabled" : ""}>REVIEW ON CURRENT TEXT</button></div>`,
  );
  const read = () => {
    const selected = defaultRules();
    for (const input of document.querySelectorAll("[data-rule]"))
      selected[input.dataset.rule] = input.checked;
    const lines = $("custom-rules")
      .value.split("\n")
      .filter((l) => l.trim());
    if (lines.length > 50) throw new Error("Use at most 50 replacement rules.");
    for (const line of lines) {
      const i = line.indexOf("=");
      if (i <= 0) throw new Error("Use find = replacement on each line.");
      const find = line.slice(0, i).trim(),
        replace = line.slice(i + 1).trim();
      if (find.length > 200 || replace.length > 500)
        throw new Error("Keep replacement rules under 200/500 characters.");
      selected.replacements.push({ find, replace });
    }
    return selected;
  };
  const preview = () => {
    try {
      $("rule-preview").textContent = applyRules(
        $("rule-sandbox").value,
        read(),
      );
      $("rule-error").textContent = "";
    } catch (error) {
      $("rule-error").textContent = error.message;
    }
  };
  for (const input of $("modal-body").querySelectorAll("input,textarea"))
    input.addEventListener("input", preview);
  preview();
  $("save-rules").onclick = () => {
    try {
      state.settings.rules = read();
      savePreferences();
      toast("Writing preferences saved locally.");
    } catch (error) {
      $("rule-error").textContent = error.message;
    }
  };
  $("apply-rules").onclick = () => {
    try {
      const doc = current(),
        ruleSet = read(),
        after = applyRules(doc.text, ruleSet);
      state.settings.rules = ruleSet;
      savePreferences();
      if (after === doc.text) {
        toast("No changes proposed by the enabled rules.");
        return;
      }
      const before = doc.text;
      modal(
        "Review writing-rule changes",
        `<p>Check the proposed reading before applying it. Your original image is preserved, and the previous text remains in history.</p><h3>BEFORE</h3><pre>${escape(before)}</pre><h3>AFTER</h3><pre>${escape(after)}</pre><div class="actions"><button id="approve-rules" class="primary">APPLY CHANGES</button><button id="keep-original">KEEP ORIGINAL</button></div>`,
      );
      $("approve-rules").onclick = () => {
        if (doc.text !== before) {
          toast("Text changed. Review the rules again.", true);
          return;
        }
        setText(doc, after, "writing rules");
        $("modal").close();
      };
      $("keep-original").onclick = () => $("modal").close();
    } catch (error) {
      $("rule-error").textContent = error.message;
    }
  };
}
$("rules").onclick = rulesDialog;
async function blobDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}
$("backup").onclick = async () => {
  if (!state.docs.length) {
    toast("Add images before backing up.");
    return;
  }
  try {
    status("Preparing workspace backup…");
    const docs = [];
    for (const doc of state.docs)
      docs.push({
        title: doc.title,
        text: doc.text,
        notes: doc.notes,
        reviewed: doc.reviewed,
        image: await blobDataUrl(doc.image),
      });
    download(
      JSON.stringify({ format: "transcribe-web/1", documents: docs }),
      `transcribe-workspace-${new Date().toISOString().slice(0, 10)}.json`,
      "application/json",
    );
    status(
      "Backup downloaded. Keep it somewhere safe; it includes your images and transcriptions.",
    );
  } catch (error) {
    toast("Backup failed: " + error.message, true);
  }
};
$("restore").onclick = () => $("restore-input").click();
$("restore-input").onchange = async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  try {
    if (file.size > 120 * 1024 * 1024)
      throw new Error("This backup is too large for browser import.");
    const data = validateBackup(JSON.parse(await file.text()));
    const added = [];
    for (const item of data) {
      const response = await fetch(item.image);
      const blob = await response.blob();
      const bitmap = await createImageBitmap(blob);
      if (bitmap.width * bitmap.height > 32_000_000) {
        bitmap.close();
        throw new Error("A backup image is too large.");
      }
      const doc = {
        id: crypto.randomUUID(),
        title: item.title,
        text: item.text,
        notes: item.notes,
        reviewed: item.reviewed,
        image: blob,
        width: bitmap.width,
        height: bitmap.height,
        history: [],
        created: Date.now(),
        engine: "Restored workspace",
      };
      bitmap.close();
      added.push(doc);
    }
    for (const doc of added) {
      state.docs.push(doc);
      await persist(doc);
    }
    if (added.length) await selectDocument(added[0].id);
    renderLibrary();
    toast(`Restored ${added.length} images. Existing work was preserved.`);
  } catch (error) {
    toast("Could not restore: " + error.message, true);
  }
};
async function sample() {
  const canvas = document.createElement("canvas");
  canvas.width = 1200;
  canvas.height = 1550;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fffdf8";
  ctx.fillRect(0, 0, 1200, 1550);
  ctx.fillStyle = "#252c30";
  ctx.font = "bold 50px Arial";
  ctx.fillText("FIELD NOTES", 95, 140);
  ctx.font = "20px Arial";
  ctx.fillStyle = "#6c706d";
  ctx.fillText("A PRINTED SAMPLE / INCLUDES INTENTIONAL ERRORS", 95, 192);
  ctx.fillRect(95, 230, 1010, 2);
  ctx.font = "30px Arial";
  ctx.fillStyle = "#30332f";
  const lines = [
    "A peace of cake is on the table.",
    "",
    "A notebook is a place to think slowly.",
    'She said "The notebook is ready."',
    "",
    "Leave enough space for a second thought.",
    "",
    "Project checklist",
    "1. Drop an image into the workbench.",
    "2. Recognize text and review uncertain words.",
    "3. Try the dictionary: select peace in the text.",
    "4. Try Writing Rules for quotation commas.",
    "",
    "This sample uses printed text to test OCR.",
    "For handwriting, choose the handwriting engine",
    "and select one line before recognizing.",
  ];
  lines.forEach((line, i) => ctx.fillText(line, 95, 315 + i * 63));
  ctx.font = "18px Arial";
  ctx.fillStyle = "#777d78";
  ctx.fillText(
    "SAMPLE 01 / LOCAL PROCESSING / YOUR WORDS, YOUR CHOICE",
    95,
    1485,
  );
  const blob = await new Promise((resolve) =>
    canvas.toBlob(resolve, "image/png"),
  );
  await importImages([
    new File([blob], "Field notes (printed sample).png", { type: "image/png" }),
  ]);
}
$("sample").onclick = sample;
$("empty-sample").onclick = sample;
$("help").onclick = () =>
  modal(
    "Your document. Your words.",
    `<p>Drop images anywhere, choose them from your device, or paste a screenshot. Printed OCR starts automatically if <strong>OCR on import</strong> is checked.</p><h3>HANDWRITING</h3><p>Select the handwriting engine, click <strong>Select line / region</strong>, and draw around one line. Recognition inserts at the editor cursor. The first run loads a large browser model; no image is uploaded. Review all readings, especially names.</p><h3>EDIT & ASSIST</h3><p>Select a word to see similar dictionary words ranked by surrounding text. Writing Rules provides quotation and spacing preferences with a review step. Context is a statistical English model, not a guarantee of meaning.</p><h3>KEEP YOUR WORK</h3><p>Images, notes, history and text are saved in this browser’s storage when available. Use <strong>Back up workspace</strong> to download images and text together. Export downloads plain text, Markdown or text/notes JSON.</p><p>Supported: PNG, JPG, WEBP, BMP, and GIF (first frame), up to 20 MB and 32 megapixels per image. PDF import and desktop-only tools are not available in this web version.</p><h3>KEYBOARD</h3><p>Ctrl/⌘+O: add images · Ctrl/⌘+S: save · Ctrl/⌘+F in the editor: find. Browser editing shortcuts work normally.</p><p><a href="${base}THIRD-PARTY-NOTICES.txt" target="_blank" rel="noopener">Third-party notices</a> · <a href="${base}GUTENBERG-NOTICE.txt" target="_blank" rel="noopener">Context corpus notice</a> · <a href="${base}MICROSOFT-UNILM-LICENSE.txt" target="_blank" rel="noopener">Upstream model repository notice</a></p>`,
  );
$("model-settings").onclick = () => {
  modal(
    "Local models & storage",
    `<div class="model-status">PRINTED OCR · LOCAL ASSETS<br>HANDWRITING · ${state.handReady ? "LOADED IN MEMORY" : "LOADS WHEN REQUESTED"}</div><p>The site serves the English OCR data, dictionary, context model, and quantized TrOCR model. Recognition runs in this browser. No OCR API key, account, or image upload is needed.</p><p>Models may take time to download on the first run and use substantial memory. Handwriting supports single-line selections. Browser caching can avoid repeat downloads but may be cleared by the browser; this is not an offline-install guarantee.</p><div class="actions"><button id="unload-model">UNLOAD HANDWRITING MODEL</button><button id="retry-dictionary">RELOAD DICTIONARY</button></div><h3>LOCAL STORAGE</h3><p>${state.db ? "Autosave is available in this browser." : "Storage is unavailable. Keep this tab open and export your work."} Clearing site data removes saved work. Download a workspace backup before doing that.</p><p>Use the desktop app for PDFs, multi-engine comparison, persistent processing queues, scan correction, or writer training exports.</p>`,
  );
  $("unload-model").onclick = () => {
    if (state.busy) {
      toast("Stop recognition before unloading.");
      return;
    }
    state.hand?.terminate();
    state.hand = null;
    state.handReady = false;
    toast("Handwriting model unloaded.");
    $("modal").close();
  };
  $("retry-dictionary").onclick = () => {
    loadDictionary();
    $("modal").close();
  };
};
window.addEventListener("beforeunload", (event) => {
  if (state.saveTimers.size || state.busy || (!state.db && state.docs.length)) {
    event.preventDefault();
    event.returnValue = "";
  }
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden" && current()) {
    revision(current(), "manual");
    persist(current());
  }
});
async function init() {
  try {
    await storage.openStorage();
    state.db = true;
    state.docs = (await storage.allDocuments()).sort(
      (a, b) => a.created - b.created,
    );
    const saved = await storage.getSettings();
    if (saved)
      state.settings = {
        ...state.settings,
        ...saved,
        rules: { ...defaultRules(), ...saved.rules },
      };
  } catch (_error) {
    toast(
      "Browser storage is unavailable. Work stays in memory; export a backup before closing.",
      true,
    );
  }
  $("review-pace").value = state.settings.pace;
  $("use-context").checked = state.settings.context;
  $("auto-correct").checked = state.settings.autoCorrect;
  renderLibrary();
  if (state.docs.length) await selectDocument(state.docs[0].id);
  loadDictionary();
}
init();
