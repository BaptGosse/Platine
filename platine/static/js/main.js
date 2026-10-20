// Browser bootstrap: wires the vendored libraries into the Platine component and starts Alpine.
// Everything with logic lives in component.js and lib.js, which are unit-tested.

import Alpine from "../vendor/alpine.esm.min.js";
import persist from "../vendor/alpine-persist.esm.min.js";
import i18next from "../vendor/i18next/i18next.js";
import LanguageDetector from "../vendor/i18next/i18next-browser-languagedetector.js";
import { Workbox } from "../vendor/workbox/workbox-window.prod.mjs";
import { createPlatine } from "./component.js";
import { i18nOptions } from "./i18n.js";

await i18next.use(LanguageDetector).init(i18nOptions());

function download(url) {
  const link = Object.assign(document.createElement("a"), { href: url, download: "" });
  document.body.append(link);
  link.click();
  link.remove();
}

Alpine.plugin(persist);
Alpine.data("platine", () =>
  createPlatine({
    fetch: (...args) => fetch(...args),
    persist: (initial, key) => Alpine.$persist(initial).as(key),
    i18n: i18next,
    window,
    document,
    navigator,
    location,
    history,
    createWorkbox: "serviceWorker" in navigator ? (url) => new Workbox(url) : null,
    setTimeout: (callback, ms) => setTimeout(callback, ms),
    setInterval: (callback, ms) => setInterval(callback, ms),
    now: () => Date.now(),
    download,
  }),
);
Alpine.start();
