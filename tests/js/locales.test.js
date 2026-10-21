// The English and French translations stay in sync and follow the house style.
import assert from "node:assert/strict";
import { LEGAL_SECTIONS } from "../../platine/static/js/component.js";
import { i18nOptions, LANGUAGES, RESOURCES } from "../../platine/static/js/i18n.js";

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

// Error codes the server can send (see platine/errors.py) and the ones the interface adds.
const ERROR_CODES = [
  "unsupported_site", "invalid_url", "drm", "private", "age_restricted", "bot_check", "live_not_started",
  "unavailable", "not_found", "forbidden", "unreachable", "unexpected", "not_a_link", "live_not_supported",
  "spotify_not_found", "spotify_unavailable", "spotify_unsupported", "ytm_unavailable", "ytm_no_match",
  "no_tracks", "queue_full", "job_not_found", "file_gone", "archive_empty",
  "empty_input", "network", "server",
];

function flatten(object, prefix = "") {
  return Object.entries(object).flatMap(([key, value]) =>
    typeof value === "object" ? flatten(value, `${prefix}${key}.`) : [[`${prefix}${key}`, value]]
  );
}

const flat = Object.fromEntries(
  Object.entries(RESOURCES).map(([lng, { translation }]) => [lng, Object.fromEntries(flatten(translation))]),
);

Deno.test("every language is configured and has translations", () => {
  assert.deepEqual(Object.keys(RESOURCES).sort(), LANGUAGES.map((l) => l.code).sort());
  const options = i18nOptions();
  assert.deepEqual(options.supportedLngs, ["fr", "en"]);
  assert.equal(options.fallbackLng, "en");
  assert.equal(options.detection.lookupLocalStorage, "platine:lang");
  assert.equal(i18nOptions({ lng: "fr" }).lng, "fr");
});

Deno.test("English and French have the same keys, plural forms aside", () => {
  const base = (lng) => [...new Set(Object.keys(flat[lng]).map((k) => k.replace(PLURAL_SUFFIX, "")))].sort();
  assert.deepEqual(base("fr"), base("en"));
});

Deno.test("plural keys have every form the language needs", () => {
  for (const lng of Object.keys(flat)) {
    const categories = new Intl.PluralRules(lng).resolvedOptions().pluralCategories;
    const plurals = new Set(Object.keys(flat[lng]).filter((k) => PLURAL_SUFFIX.test(k)).map((k) => k.replace(PLURAL_SUFFIX, "")));
    for (const key of plurals) {
      for (const category of categories) assert.ok(`${key}_${category}` in flat[lng], `${lng}: ${key}_${category}`);
    }
  }
});

Deno.test("both languages use the same placeholders", () => {
  const placeholders = (text) => [...text.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort();
  for (const [key, english] of Object.entries(flat.en)) {
    const base = key.replace(PLURAL_SUFFIX, "");
    const french = Object.entries(flat.fr).filter(([k]) => k.replace(PLURAL_SUFFIX, "") === base);
    for (const [frenchKey, text] of french) assert.deepEqual(placeholders(text), placeholders(english), frenchKey);
  }
});

Deno.test("every error code is translated", () => {
  for (const lng of Object.keys(flat)) {
    for (const code of ERROR_CODES) assert.ok(`errors.${code}` in flat[lng], `${lng}: errors.${code}`);
  }
});

Deno.test("the legal page lists exactly the sections that are translated", () => {
  const LEGAL_TEXTS = ["title", "back", "intro", "note"];
  for (const [lng, { translation }] of Object.entries(RESOURCES)) {
    const sections = Object.keys(translation.legal).filter((key) => !LEGAL_TEXTS.includes(key));
    assert.deepEqual(sections, LEGAL_SECTIONS, lng);
    for (const section of LEGAL_SECTIONS) {
      assert.deepEqual(Object.keys(translation.legal[section]), ["title", "body"], `${lng}: legal.${section}`);
    }
  }
});

Deno.test("house style: simple hyphens only, and the brand is always Platine", () => {
  for (const [lng, texts] of Object.entries(flat)) {
    for (const [key, text] of Object.entries(texts)) {
      assert.ok(!/[\u2013\u2014]/.test(text), `${lng}: ${key} contains an en or em dash`);
      assert.ok(!/\bplatine\b/.test(text), `${lng}: ${key} spells the brand in lowercase`);
    }
  }
});
