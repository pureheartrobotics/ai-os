// Validates a plugin market index with DSH's own parser, extracted from the running install.
// Reimplemented here as a faithful port of dsh-plugin-market-index/src/index.ts, because the
// package lives inside app.asar and cannot be require()d directly.
import fs from "node:fs";

const SEMVER = /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-(?:(?:0|[1-9]\d*)|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:(?:0|[1-9]\d*)|\d*[a-zA-Z-][0-9a-zA-Z-]*))*)?(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?$/u;
const PACKAGE_NAME = /^(?:@[a-z0-9][a-z0-9._~-]*\/)?[a-z0-9][a-z0-9._~-]*$/u;
const LANGUAGE_ID = /^[a-z]{2,8}(?:-[a-z0-9]{1,8})*$/u;
const PATH_SEGMENT = /^[A-Za-z0-9._@+-]+$/u;
const COMMIT = /^[0-9a-f]{40}$/u;
const DATA_ICON = /^data:(?:image\/svg\+xml|image\/png|image\/jpeg|image\/webp);base64,([A-Za-z0-9+/]*={0,2})$/u;
const BASE64 = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u;
const MAX_INLINE_ICON_BYTES = 32 * 1024;
const MAX_PUBLISH_TIMESTAMP = 1e11;

class MarketIndexError extends Error {
  constructor(path, reason) {
    super(`${path} ${reason}`);
    this.path = path;
    this.reason = reason;
  }
}
const fail = (path, reason) => { throw new MarketIndexError(path, reason); };
const objectAt = (v, p) => {
  if (typeof v !== "object" || v === null || Array.isArray(v)) fail(p, "must be an object");
  return v;
};
const stringAt = (v, p) => {
  if (typeof v !== "string" || v.trim() === "") fail(p, "must be a string with a non-whitespace character");
  return v;
};
const optional = (o, k, p, read) => (Object.hasOwn(o, k) ? read(o[k], `${p}.${k}`) : undefined);

function localizedText(value, path) {
  if (typeof value === "string") return stringAt(value, path);
  const object = objectAt(value, path);
  const text = {};
  for (const [lang, member] of Object.entries(object)) {
    if (!LANGUAGE_ID.test(lang)) fail(`${path}.${lang}`, "must be keyed by a lowercase language id");
    text[lang] = stringAt(member, `${path}.${lang}`);
  }
  if (!Object.hasOwn(text, "en")) fail(path, "must contain en");
  return text;
}

function declarations(value, path, read) {
  const result = {};
  for (const [id, member] of Object.entries(objectAt(value, path))) {
    if (id === "") fail(path, "must not declare an empty id");
    result[id] = read(objectAt(member, `${path}.${id}`), `${path}.${id}`);
  }
  return result;
}
const declaration = (o, p) => ({ title: localizedText(o.title, `${p}.title`) });
const sortKeyDeclaration = (o, p) => {
  if (o.order !== "asc" && o.order !== "desc") fail(`${p}.order`, 'must be "asc" or "desc"');
  return { title: localizedText(o.title, `${p}.title`), order: o.order };
};

function indexMetadata(value, path) {
  const o = value === undefined ? {} : objectAt(value, path);
  return {
    categories: optional(o, "categories", path, (m, at) => declarations(m, at, declaration)) ?? {},
    labels: optional(o, "labels", path, (m, at) => declarations(m, at, declaration)) ?? {},
    sortKeys: optional(o, "sortKeys", path, (m, at) => declarations(m, at, sortKeyDeclaration)) ?? {},
  };
}

function declaredId(value, path, declared) {
  const id = stringAt(value, path);
  if (!Object.hasOwn(declared, id)) fail(path, `references undeclared id ${JSON.stringify(id)}`);
  return id;
}

function pluginMetadata(value, path, index) {
  const o = value === undefined || value === null ? {} : objectAt(value, path);
  const field = (k, read) => (o[k] === null ? undefined : optional(o, k, path, read));
  const category = field("category", (m, at) => declaredId(m, at, index.categories));
  const keywords = field("keywords", (m, at) => {
    if (!Array.isArray(m)) fail(at, "must be an array");
    return m.map((k, i) => {
      if (typeof k !== "string") fail(`${at}[${i}]`, "must be a string");
      return k;
    });
  }) ?? [];
  const labels = field("labels", (m, at) => {
    if (!Array.isArray(m)) fail(at, "must be an array");
    const ids = m.map((l, i) => declaredId(l, `${at}[${i}]`, index.labels));
    if (new Set(ids).size !== ids.length) fail(at, "must not repeat a label");
    return ids;
  }) ?? [];
  const sortKeys = field("sortKeys", (m, at) => {
    const values = {};
    for (const [id, v] of Object.entries(objectAt(m, at))) {
      declaredId(id, `${at}.${id}`, index.sortKeys);
      if (v === null) continue;
      if (typeof v !== "number" || !Number.isFinite(v)) fail(`${at}.${id}`, "must be a finite number");
      values[id] = v;
    }
    return values;
  }) ?? {};
  return { ...(category === undefined ? {} : { category }), keywords, labels, sortKeys };
}

function httpUrl(value, path, protocols) {
  const text = stringAt(value, path);
  let url;
  try {
    url = new URL(text);
  } catch {
    fail(path, "must be an absolute URL");
  }
  if (!protocols.includes(url.protocol)) fail(path, `must use ${protocols.join(" or ")}`);
  if (url.username !== "" || url.password !== "") fail(path, "must not contain credentials");
  if (url.href.includes("?") || url.href.includes("#")) fail(path, "must not contain a query or fragment");
  return url;
}

function homepageUrl(value, path) {
  const text = stringAt(value, path);
  if (!URL.canParse(text)) fail(path, "must be an absolute URL");
  const url = new URL(text);
  if (url.protocol !== "https:" && url.protocol !== "http:") fail(path, "must use https: or http:");
  return url.href;
}

function packagePath(value, path) {
  const text = stringAt(value, path);
  const segments = text.split("/");
  if (segments.some((s) => s === "." || s === ".." || !PATH_SEGMENT.test(s))) {
    fail(path, "must be a relative directory of letters, digits, and ._@+- segments without . or ..");
  }
  return text;
}

function repository(value, path) {
  const o = objectAt(value, path);
  const url = httpUrl(o.url, `${path}.url`, ["https:", "http:"]).href;
  const directory = optional(o, "directory", path, packagePath);
  return { url, ...(directory === undefined ? {} : { directory }) };
}

function source(value, path) {
  const o = objectAt(value, path);
  if (o.type === "npm") {
    const registry = optional(o, "registry", path, (m, at) => httpUrl(m, at, ["https:", "http:"]).href);
    return { type: "npm", ...(registry === undefined ? {} : { registry }) };
  }
  if (o.type === "git") {
    const commit = stringAt(o.commit, `${path}.commit`);
    if (!COMMIT.test(commit)) fail(`${path}.commit`, "must be a lowercase 40-hex-digit commit SHA");
    const url = httpUrl(o.url, `${path}.url`, ["https:"]);
    const packageDir = optional(o, "path", path, packagePath);
    return { type: "git", url: url.href, commit, ...(packageDir === undefined ? {} : { path: packageDir }) };
  }
  return fail(`${path}.type`, 'must be "npm" or "git"');
}

// Follows the range grammar of node-semver's validRange (loose prefixes like `v` included).
const PARTIAL = String.raw`v?(?:[xX*]|\d+)(?:\.(?:[xX*]|\d+)){0,2}(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?`;
const COMPARATOR = new RegExp(String.raw`^(?:[<>]=?|=|~>?|\^)?\s*${PARTIAL}$`, "u");
const HYPHEN = new RegExp(String.raw`^${PARTIAL}\s+-\s+${PARTIAL}$`, "u");

function isSemverRange(range) {
  return range.split("||").every(set => {
    const trimmed = set.trim();
    if (trimmed === "") return true;
    if (HYPHEN.test(trimmed)) return true;
    return trimmed.replace(/([<>]=?|=|~>?|\^)\s+/gu, "$1").split(/\s+/u).every(c => COMPARATOR.test(c));
  });
}

function engines(value, path) {
  const o = objectAt(value, path);
  const dsh = optional(o, "dsh", path, (m, at) => {
    const range = stringAt(m, at);
    if (range.startsWith("workspace:")) fail(at, "must not be a workspace: range");
    if (!isSemverRange(range)) fail(at, "must be a SemVer range");
    return range;
  });
  return dsh === undefined ? {} : { dsh };
}

function icon(value, path, indexUrl) {
  const text = stringAt(value, path);
  if (text.startsWith("data:")) {
    const m = DATA_ICON.exec(text);
    const payload = m?.[1];
    if (payload === undefined || payload === "" || !BASE64.test(payload)) {
      fail(path, "must be a base64 SVG, PNG, JPEG, or WebP data URL");
    }
    const bytes = (payload.length / 4) * 3 - (payload.endsWith("==") ? 2 : payload.endsWith("=") ? 1 : 0);
    if (bytes > MAX_INLINE_ICON_BYTES) fail(path, `must not exceed ${MAX_INLINE_ICON_BYTES / 1024} KiB of decoded bytes`);
    return text;
  }
  let resolved;
  try {
    resolved = new URL(text, indexUrl);
  } catch {
    fail(path, "must be a URL reference");
  }
  if (resolved.protocol !== "https:" && (resolved.origin === "null" || resolved.origin !== indexUrl.origin)) {
    fail(path, "must resolve to https or the index origin");
  }
  return resolved.href;
}

function marketVersion(value, path) {
  const o = objectAt(value, path);
  const version = stringAt(o.version, `${path}.version`);
  if (!SEMVER.test(version)) fail(`${path}.version`, "must be an exact SemVer version");
  const ts = o.publishTimestamp;
  if (typeof ts !== "number" || !Number.isInteger(ts) || ts < 0 || ts >= MAX_PUBLISH_TIMESTAMP) {
    fail(`${path}.publishTimestamp`, "must be an integer number of Unix seconds in [0, 10^11)");
  }
  return { version, publishTimestamp: ts, source: source(o.source, `${path}.source`),
    engines: optional(o, "engines", path, engines) ?? {} };
}

function versions(value, path) {
  if (!Array.isArray(value) || value.length === 0) fail(path, "must be a non-empty array");
  const seen = new Set();
  const parsed = value.map((m, i) => {
    const at = `${path}[${i}]`;
    const entry = marketVersion(m, at);
    if (seen.has(entry.version)) fail(`${at}.version`, `duplicates ${entry.version}`);
    seen.add(entry.version);
    return entry;
  });
  return parsed.sort((a, b) => compareSemver(b.version, a.version));
}

function compareSemver(a, b) {
  const pa = a.split("-")[0].split(".").map(Number);
  const pb = b.split("-")[0].split(".").map(Number);
  for (let i = 0; i < 3; i += 1) {
    if (pa[i] !== pb[i]) return pa[i] - pb[i];
  }
  return a === b ? 0 : a > b ? 1 : -1;
}

function plugin(value, path, index, indexUrl) {
  const o = objectAt(value, path);
  const name = stringAt(o.name, `${path}.name`);
  if (name.length > 214 || !PACKAGE_NAME.test(name)) fail(`${path}.name`, "must be a valid npm package name");
  const title = optional(o, "title", path, localizedText);
  const description = optional(o, "description", path, localizedText);
  const iconUrl = optional(o, "icon", path, (m, at) => icon(m, at, indexUrl));
  const author = optional(o, "author", path, stringAt);
  const homepage = optional(o, "homepage", path, homepageUrl);
  const repo = optional(o, "repository", path, repository);
  return { name, ...(title === undefined ? {} : { title }), ...(description === undefined ? {} : { description }),
    ...(iconUrl === undefined ? {} : { icon: iconUrl }), ...(author === undefined ? {} : { author }),
    ...(homepage === undefined ? {} : { homepage }), ...(repo === undefined ? {} : { repository: repo }),
    metadata: pluginMetadata(o.metadata, `${path}.metadata`, index),
    versions: versions(o.versions, `${path}.versions`) };
}

function parseMarketIndex(value, indexUrl) {
  if (!URL.canParse(indexUrl)) fail("$", `index URL ${JSON.stringify(indexUrl)} must be an absolute URL`);
  const base = new URL(indexUrl);
  const o = objectAt(value, "$");
  if (o.format !== 1) fail("$.format", "must be 1");
  const metadata = indexMetadata(o.metadata, "$.metadata");
  if (!Array.isArray(o.plugins)) fail("$.plugins", "must be an array");
  const names = new Set();
  const plugins = o.plugins.map((entry, i) => {
    const parsed = plugin(entry, `$.plugins[${i}]`, metadata, base);
    if (names.has(parsed.name)) fail(`$.plugins[${i}].name`, `duplicates ${parsed.name}`);
    names.add(parsed.name);
    return parsed;
  });
  const title = localizedText(o.title, "$.title");
  const description = optional(o, "description", "$", localizedText);
  return { format: 1, title, ...(description === undefined ? {} : { description }), metadata, plugins };
}

const [file, indexUrl = "https://example.com/market-index.json"] = process.argv.slice(2);
if (!file) {
  console.error("usage: node validate_market_index.mjs <index.json> [indexUrl]");
  process.exit(2);
}
try {
  const doc = JSON.parse(fs.readFileSync(file, "utf8"));
  const ok = parseMarketIndex(doc, indexUrl);
  console.log("VALID");
  console.log("  plugins:", ok.plugins.length);
  for (const p of ok.plugins) {
    console.log(`  - ${p.name}: ${p.versions.map((v) => v.version).join(", ")}`);
    console.log(`    title: ${JSON.stringify(p.title)}`);
    console.log(`    category: ${p.metadata.category}, labels: ${p.metadata.labels.join("/")}`);
    console.log(`    install: ${p.name}@${p.versions[0].version} from ${p.versions[0].source.type}`);
  }
} catch (e) {
  if (e instanceof MarketIndexError) {
    console.error(`INVALID at ${e.path}: ${e.reason}`);
    process.exit(1);
  }
  throw e;
}
