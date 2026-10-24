export const WORDS = /[^\W\d_]+(?:['’][^\W\d_]+)*/gu;
export const words = (text) => [
  ...text.matchAll(/[\p{L}]+(?:['’][\p{L}]+)*/gu),
];
export const wordCount = (text) => words(text).length;
export async function decodeContext(buffer) {
  const bytes = new Uint8Array(buffer);
  // Some static servers set Content-Encoding for .gz files, so fetch has
  // already decoded them. GitHub Pages and local preview can differ here.
  if (bytes[0] === 0x1f && bytes[1] === 0x8b) {
    return new Response(
      new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip")),
    ).json();
  }
  return JSON.parse(new TextDecoder().decode(bytes));
}
export const defaultRules = () => ({
  commaBefore: false,
  commaInside: false,
  dialogueComma: false,
  smartQuotes: false,
  singleSpaces: false,
  replacements: [],
});
export function applyRules(text, rules) {
  let result = text;
  if (rules.commaBefore)
    result = result.replace(
      /([\p{L}\p{N})\]])([ \t]+)("(?:[^"\\]|\\.)*"|“[^”]*”)/gu,
      "$1,$2$3",
    );
  if (rules.commaInside)
    result = result
      .replace(/("[^"\n]*[^,!?;:.])",/g, '$1,"')
      .replace(/(“[^”\n]*[^,!?;:.])”,/g, "$1,”");
  if (rules.dialogueComma)
    result = result.replace(
      /("[^"\n]*[^,.!?;:])"(?=[ \t]+(?:he|she|they|we|I|you|[A-Z][a-z]+)[ \t]+(?:said|asked|replied|added|whispered)\b)/g,
      '$1,"',
    );
  if (rules.smartQuotes) result = result.replace(/"([^"\n]*)"/g, "“$1”");
  if (rules.singleSpaces)
    result = result.replace(/(\S)[ \t]{2,}(?=\S)/g, "$1 ");
  for (const pair of rules.replacements || []) {
    if (!pair.find) continue;
    const pattern = pair.find.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    result = result.replace(
      new RegExp(`(?<![\\p{L}\\p{N}_])${pattern}(?![\\p{L}\\p{N}_])`, "giu"),
      () => pair.replace,
    );
    if (result.length > Math.min(5_000_000, text.length * 10 + 100_000))
      throw new Error(
        "Rules expand the text too much. Review your replacements.",
      );
  }
  return result;
}
export function distance(a, b) {
  const matrix = Array.from({ length: a.length + 1 }, () =>
    new Array(b.length + 1).fill(0),
  );
  for (let i = 0; i <= a.length; i++) matrix[i][0] = i;
  for (let j = 0; j <= b.length; j++) matrix[0][j] = j;
  for (let i = 1; i <= a.length; i++)
    for (let j = 1; j <= b.length; j++) {
      matrix[i][j] = Math.min(
        matrix[i - 1][j] + 1,
        matrix[i][j - 1] + 1,
        matrix[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1])
        matrix[i][j] = Math.min(matrix[i][j], matrix[i - 2][j - 2] + 1);
    }
  return matrix[a.length][b.length];
}
export function selectionWord(text, start, end) {
  if (start !== end) return { start, end, word: text.slice(start, end) };
  const matches = words(text);
  const match = matches.find(
    (m) => m.index <= start && m.index + m[0].length >= start,
  );
  return match
    ? { start: match.index, end: match.index + match[0].length, word: match[0] }
    : { start, end, word: "" };
}
export function rankSuggestions(
  word,
  candidates,
  before,
  after,
  model,
  learned = {},
  useContext = true,
) {
  const normalized = word.toLowerCase().replaceAll("’", "'");
  const left = words(before.split(/[.!?\n]/).at(-1) || "")
    .map((m) => m[0].toLowerCase())
    .slice(-2);
  const right = words(after.split(/[.!?\n]/)[0] || "")
    .map((m) => m[0].toLowerCase())
    .slice(0, 2);
  const count = (arr) =>
    model?.[["unigrams", "bigrams", "trigrams"][arr.length - 1]]?.[
      arr.join("\t")
    ] || 0;
  const vocabularySize = model ? Object.keys(model.unigrams).length : 1;
  const total = (model?.total || 1) + 0.5 * vocabularySize;
  // Compute the denominator once per lookup rather than once per candidate token.
  const prob = (w, h) => {
    const base = (count([w]) + 0.5) / total;
    if (!h.length) return base;
    const n = count([h.at(-1), w]);
    let p = n ? (n + 5 * base) / (count([h.at(-1)]) + 5) : base;
    const tri = h.length > 1 ? count([...h.slice(-2), w]) : 0;
    if (tri) p = (tri + 3 * p) / (count(h.slice(-2)) + 3);
    return p;
  };
  const choices = new Set(candidates.map((c) => c.toLowerCase()));
  if (learned[normalized]) choices.add(learned[normalized].toLowerCase());
  return [...choices]
    .filter((c) => c !== normalized && c.length < 40)
    .map((candidate) => {
      const d = distance(normalized, candidate),
        similarity = Math.max(
          0,
          Math.round(
            100 * (1 - d / Math.max(normalized.length, candidate.length)),
          ),
        );
      let score = -2.8 * d + 0.6 * Math.log1p(count([candidate]));
      let evidence = 0,
        phrase = "";
      if (useContext && model && (left.length || right.length)) {
        const phrases = [];
        if (left.length) phrases.push([left.at(-1), candidate]);
        if (right.length) phrases.push([candidate, right[0]]);
        if (left.length && right.length)
          phrases.push([left.at(-1), candidate, right[0]]);
        if (left.length === 2) phrases.push([...left, candidate]);
        if (right.length === 2) phrases.push([candidate, ...right]);
        const supported = phrases
          .filter((p) => count(p) >= 2)
          .sort((a, b) => b.length - a.length || count(b) - count(a));
        if (supported.length) {
          evidence = count(supported[0]);
          phrase = supported[0].join(" ");
          let gain = Math.log(prob(candidate, left) / prob(candidate, []));
          right.forEach(
            (w, i) =>
              (gain +=
                0.8 *
                Math.log(
                  prob(
                    w,
                    [...left, candidate, ...right.slice(0, i)].slice(-2),
                  ) / prob(w, right.slice(0, i)),
                )),
          );
          score += 0.85 * Math.max(-8, Math.min(12, gain));
        }
      }
      if (learned[normalized]?.toLowerCase() === candidate) score += 1;
      return {
        word: candidate,
        score,
        similarity,
        evidence,
        reason: evidence
          ? `Fits “${phrase}” · ${similarity}% similar`
          : `${similarity}% spelling similarity`,
      };
    })
    .sort((a, b) => b.score - a.score || a.word.localeCompare(b.word))
    .slice(0, 7);
}
export function validateBackup(payload) {
  if (
    payload?.format !== "transcribe-web/1" ||
    !Array.isArray(payload.documents) ||
    payload.documents.length > 200
  )
    throw new Error("Not a supported Transcribe workspace backup.");
  return payload.documents.map((doc) => {
    if (
      typeof doc.title !== "string" ||
      typeof doc.text !== "string" ||
      typeof doc.image !== "string" ||
      !/^data:image\/(png|jpeg|webp|bmp|gif|x-ms-bmp);base64,/i.test(
        doc.image,
      ) ||
      doc.text.length > 5_000_000 ||
      doc.image.length > 30_000_000
    )
      throw new Error("The backup contains an invalid document.");
    return {
      title: doc.title.slice(0, 200),
      text: doc.text,
      notes: typeof doc.notes === "string" ? doc.notes.slice(0, 1_000_000) : "",
      reviewed: doc.reviewed === true,
      image: doc.image,
    };
  });
}
