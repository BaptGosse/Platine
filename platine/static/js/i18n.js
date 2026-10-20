// i18next configuration shared by the browser bootstrap (main.js) and the tests.

import en from "../locales/en.json" with { type: "json" };
import fr from "../locales/fr.json" with { type: "json" };

export const LANGUAGES = [
  { code: "fr", label: "FR", name: "Français" },
  { code: "en", label: "EN", name: "English" },
];

export const RESOURCES = { en: { translation: en }, fr: { translation: fr } };

/** Options for `i18next.init()`. The language detector reads `detection` when it is plugged in. */
export function i18nOptions(overrides = {}) {
  return {
    resources: RESOURCES,
    supportedLngs: LANGUAGES.map((language) => language.code),
    nonExplicitSupportedLngs: true, // "fr-CA" or "en-GB" use the base language
    load: "languageOnly",
    fallbackLng: "en",
    // Texts are inserted with x-text (textContent), never as HTML: no escaping needed.
    interpolation: { escapeValue: false },
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: "platine:lang",
      caches: ["localStorage"],
    },
    ...overrides,
  };
}
