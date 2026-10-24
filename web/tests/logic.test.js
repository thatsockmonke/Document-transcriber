import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import {
  applyRules,
  defaultRules,
  distance,
  wordCount,
  selectionWord,
  rankSuggestions,
  validateBackup,
  decodeContext,
} from "../src/logic.js";

test("quote preferences are reviewable and idempotent", () => {
  const rules = {
    ...defaultRules(),
    commaBefore: true,
    commaInside: true,
    dialogueComma: true,
    smartQuotes: true,
  };
  const source =
    'She said "Hello."\n"Goodbye" she said.\n"A word", then a comma.';
  const result = applyRules(source, rules);
  assert.equal(
    result,
    "She said, “Hello.”\n“Goodbye,” she said.\n“A word,” then a comma.",
  );
  assert.equal(applyRules(result, rules), result);
});
test("literal rules do not execute regex or replacement syntax", () => {
  const rules = {
    ...defaultRules(),
    replacements: [{ find: "$1", replace: "literal $&" }],
  };
  assert.equal(applyRules("Cost $1 today", rules), "Cost literal $& today");
});
test("Unicode words and selected ranges retain correct offsets", () => {
  assert.equal(wordCount("Café déjà vu 🦊"), 3);
  assert.deepEqual(selectionWord("🦊 café nearby", 5, 5), {
    start: 3,
    end: 7,
    word: "café",
  });
  assert.equal(distance("form", "from"), 1);
});
test("real bundled context prioritizes valid-word confusions", () => {
  const model = JSON.parse(
    gunzipSync(
      readFileSync(new URL("../public/context-en.json.gz", import.meta.url)),
    ),
  );
  assert.equal(
    rankSuggestions(
      "peace",
      ["place", "piece", "pace"],
      "A ",
      " of cake.",
      model,
    )[0].word,
    "piece",
  );
  assert.equal(
    rankSuggestions(
      "form",
      ["for", "from", "firm"],
      "He arrived ",
      " London.",
      model,
    )[0].word,
    "from",
  );
  assert.equal(
    rankSuggestions("peace", ["piece"], "A ", " of cake.", model, {}, false)[0]
      .evidence,
    0,
  );
});
test("workspace import rejects arbitrary URLs and malformed backups", () => {
  assert.throws(() => validateBackup({ format: "wrong", documents: [] }));
  assert.throws(() =>
    validateBackup({
      format: "transcribe-web/1",
      documents: [
        { title: "X", text: "Y", image: "https://example.com/private.png" },
      ],
    }),
  );
  assert.equal(
    validateBackup({
      format: "transcribe-web/1",
      documents: [
        { title: "X", text: "Y", image: "data:image/png;base64,YQ==" },
      ],
    })[0].text,
    "Y",
  );
});

test("context loading supports compressed files and HTTP-decoded bodies", async () => {
  const { gzipSync } = await import("node:zlib");
  const data = JSON.stringify({ format: "context", value: 3 });
  assert.deepEqual(await decodeContext(new TextEncoder().encode(data)), {
    format: "context",
    value: 3,
  });
  assert.deepEqual(await decodeContext(gzipSync(data)), {
    format: "context",
    value: 3,
  });
});
