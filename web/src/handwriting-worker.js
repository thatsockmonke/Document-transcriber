import { env, pipeline } from "@huggingface/transformers";
env.allowRemoteModels = false;
env.allowLocalModels = true;
// Explicit paths work on project Pages URLs without cross-origin isolation.
env.localModelPath =
  self.location.origin + import.meta.env.BASE_URL + "models/";
env.backends.onnx.wasm.wasmPaths =
  self.location.origin + import.meta.env.BASE_URL + "vendor/ort/";
env.backends.onnx.wasm.numThreads = 1;
let recognizer;
self.onmessage = async ({ data }) => {
  try {
    if (!recognizer) {
      recognizer = await pipeline("image-to-text", "trocr-small-handwritten", {
        device: "wasm",
        dtype: "q8",
        progress_callback: (p) =>
          self.postMessage({
            type: "progress",
            message:
              p.status === "progress"
                ? `Loading handwriting model · ${p.file}`
                : "Preparing local handwriting model…",
            progress: p.progress ? p.progress / 100 : null,
          }),
      });
    }
    if (data.type === "load") {
      self.postMessage({ type: "ready" });
      return;
    }
    const url = URL.createObjectURL(data.image);
    try {
      const result = await recognizer(url, {
        max_new_tokens: 128,
        num_beams: 3,
      });
      self.postMessage({
        type: "result",
        text: result.map((r) => r.generated_text).join("\n"),
      });
    } finally {
      URL.revokeObjectURL(url);
    }
  } catch (error) {
    self.postMessage({
      type: "error",
      message: error.message || String(error),
    });
  }
};
