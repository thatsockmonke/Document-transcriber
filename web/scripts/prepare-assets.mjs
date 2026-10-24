import {
  mkdir,
  readFile,
  writeFile,
  copyFile,
  readdir,
  rename,
  rm,
} from "node:fs/promises";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const pub = path.join(root, "public");
async function copy(source, target) {
  await mkdir(path.dirname(target), { recursive: true });
  await copyFile(source, target);
}
await copy(
  path.join(root, "node_modules/tesseract.js/dist/worker.min.js"),
  path.join(pub, "vendor/tesseract/worker.min.js"),
);
for (const name of await readdir(
  path.join(root, "node_modules/tesseract.js-core"),
)) {
  if (/\.wasm(\.js)?$/.test(name))
    await copy(
      path.join(root, "node_modules/tesseract.js-core", name),
      path.join(pub, "vendor/tesseract-core", name),
    );
}
await copy(
  path.join(
    root,
    "node_modules/@tesseract.js-data/eng/4.0.0/eng.traineddata.gz",
  ),
  path.join(pub, "vendor/lang/eng.traineddata.gz"),
);
for (const name of await readdir(
  path.join(root, "node_modules/onnxruntime-web/dist"),
)) {
  if (/^ort-wasm.*\.(wasm|mjs)$/.test(name))
    await copy(
      path.join(root, "node_modules/onnxruntime-web/dist", name),
      path.join(pub, "vendor/ort", name),
    );
}
for (const name of ["index.aff", "index.dic", "license"])
  await copy(
    path.join(root, "node_modules/dictionary-en", name),
    path.join(pub, "dictionary", name),
  );
await copy(
  path.join(root, "../src/document_transcriber/data/context-en.json.gz"),
  path.join(pub, "context-en.json.gz"),
);
await copy(
  path.join(root, "../src/document_transcriber/data/GUTENBERG-NOTICE.txt"),
  path.join(pub, "GUTENBERG-NOTICE.txt"),
);
await copy(
  path.join(
    root,
    "../src/document_transcriber/data/MICROSOFT-UNILM-LICENSE.txt",
  ),
  path.join(pub, "MICROSOFT-UNILM-LICENSE.txt"),
);
const revision = "2432e24d184b1d964d07ed04f5d9e21d31a59141";
const files = {
  "README.md": "git:7287745cc27b5c9150a0c290dc0e15cc5c6d6569",
  "config.json": "git:a7817100c3840b680166143285b038b5bae02331",
  "generation_config.json": "git:18e475bcdda9a14641d2afdf17cc4567aabc9fa4",
  "preprocessor_config.json": "git:83af4d3da32150c64f279aa4cbed3a6166b77302",
  "tokenizer_config.json": "git:22dd4ff74bd92b564b2af510e9d35ce7976ce3a4",
  "special_tokens_map.json": "git:68171d1ff68b731a33d119708476692c094a466b",
  "tokenizer.json": "git:b32c87bef9bf22a5b1c1fb902a76098d13909dc6",
  "onnx/encoder_model_quantized.onnx":
    "2f29edbd925f8a49c9c7d1349895f960cf09d2efdc76fe23f957048d476e0d03",
  "onnx/decoder_model_merged_quantized.onnx":
    "51076aa396ab5939c4668db9de901ad51765094b4c05c4c8c1f8ae2012ba1e08",
};
function verify(bytes, expected) {
  return expected.startsWith("git:")
    ? createHash("sha1")
        .update(`blob ${bytes.length}\0`)
        .update(bytes)
        .digest("hex") === expected.slice(4)
    : createHash("sha256").update(bytes).digest("hex") === expected;
}
for (const [name, digest] of Object.entries(files)) {
  const target = path.join(pub, "models/trocr-small-handwritten", name);
  await mkdir(path.dirname(target), { recursive: true });
  let valid = false;
  try {
    valid = verify(await readFile(target), digest);
  } catch {
    // Missing generated files are downloaded below.
  }
  if (valid) continue;
  console.log("Fetching pinned browser model:", name);
  const temp = target + ".download";
  try {
    execFileSync(
      "curl",
      [
        "--fail",
        "--location",
        "--retry",
        "2",
        "--max-time",
        "300",
        "--silent",
        "--show-error",
        `https://huggingface.co/Xenova/trocr-small-handwritten/resolve/${revision}/${name}`,
        "--output",
        temp,
      ],
      { stdio: "inherit" },
    );
    if (!verify(await readFile(temp), digest))
      throw new Error(`Checksum mismatch for ${name}`);
    await rename(temp, target);
  } finally {
    await rm(temp, { force: true });
  }
}
await writeFile(
  path.join(pub, "model-manifest.json"),
  JSON.stringify(
    { model: "Xenova/trocr-small-handwritten", revision, files },
    null,
    2,
  ),
);
const ortLicense = path.join(root, "node_modules/onnxruntime-web/LICENSE");
try {
  await readFile(ortLicense);
} catch {
  execFileSync("curl", [
    "--fail",
    "--location",
    "--retry",
    "2",
    "--silent",
    "--show-error",
    "https://raw.githubusercontent.com/microsoft/onnxruntime/89f8206ba4/LICENSE",
    "--output",
    ortLicense,
  ]);
}
let notices =
  "TRANSCRIBE WEB — THIRD PARTY NOTICES\n\nBrowser model: Xenova/trocr-small-handwritten\nPinned revision: " +
  revision +
  "\n\n";
for (const [name, file] of [
  ["Transformers.js", "@huggingface/transformers/LICENSE"],
  ["Tesseract.js", "tesseract.js/LICENSE.md"],
  ["Tesseract core", "tesseract.js-core/LICENSE"],
  ["NSpell", "nspell/license"],
  ["English dictionary", "dictionary-en/license"],
  ["ONNX Runtime", "onnxruntime-web/LICENSE"],
]) {
  try {
    notices +=
      name +
      "\n" +
      (await readFile(path.join(root, "node_modules", file), "utf8")) +
      "\n\n";
  } catch {
    console.warn("License file path unavailable:", name);
  }
}
notices +=
  "\nModel card\n" +
  (await readFile(
    path.join(pub, "models/trocr-small-handwritten/README.md"),
    "utf8",
  ));
await writeFile(path.join(pub, "THIRD-PARTY-NOTICES.txt"), notices);
console.log(
  "Local OCR, dictionary, context, and browser handwriting assets prepared.",
);
