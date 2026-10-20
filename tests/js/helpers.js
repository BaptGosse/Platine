// Test doubles for the Platine interface: a real i18next instance with the real locale files,
// and a fake browser (network, storage, timers, window events, service worker).

import i18next from "../../platine/static/vendor/i18next/i18next.js";
import { createPlatine } from "../../platine/static/js/component.js";
import { i18nOptions } from "../../platine/static/js/i18n.js";

export const NOW = Date.UTC(2026, 9, 20, 14, 0);
export const NNBSP = " "; // narrow no-break space, used by French typography

export async function createI18n(lng = "en") {
  const instance = i18next.createInstance();
  await instance.init(i18nOptions({ lng }));
  return instance;
}

/** The `{ t, exists, locale }` context that lib.js expects. */
export async function context(lng) {
  const i18n = await createI18n(lng);
  return {
    t: (key, options) => i18n.t(key, { ...options, lng }),
    exists: (key) => i18n.exists(key, { lng }),
    locale: lng,
  };
}

export const job = (fields = {}) => ({ id: "a", status: "queued", progress: null, ...fields });

export function jsonResponse(body, status = 200) {
  return { ok: status < 400, status, json: async () => body };
}

export function errorResponse(code, message, status = 400) {
  return jsonResponse({ detail: { code, message } }, status);
}

/**
 * A fake Platine server. `routes` maps "METHOD /path" (query string ignored) to a response,
 * a function `(path, options) => response`, or an Error to simulate a network failure.
 */
function fakeFetch(routes) {
  const calls = [];
  async function fetch(path, options = {}) {
    const method = options.method ?? "GET";
    calls.push({ method, path, body: options.body ? JSON.parse(options.body) : undefined });
    const handler = routes[`${method} ${path.split("?")[0]}`];
    if (handler === undefined) return errorResponse("job_not_found", "Conversion not found.", 404);
    if (handler instanceof Error) throw handler;
    return typeof handler === "function" ? handler(path, options) : handler;
  }
  return { fetch, calls };
}

function fakeWorkbox() {
  const events = new EventTarget();
  return {
    url: null,
    registered: false,
    skippedWaiting: false,
    addEventListener: (type, listener) => events.addEventListener(type, listener),
    emit: (type) => events.dispatchEvent(new Event(type)),
    register() {
      this.registered = true;
    },
    messageSkipWaiting() {
      this.skippedWaiting = true;
    },
  };
}

/** Everything the component needs from the browser, plus handles to inspect what it did. */
export async function fakeEnv({ routes = {}, lng = "en", search = "", groups = [], serviceWorker = true } = {}) {
  const i18n = await createI18n(lng);
  const { fetch, calls } = fakeFetch(routes);
  const workbox = serviceWorker ? fakeWorkbox() : null;
  const fake = {
    calls,
    workbox,
    i18n,
    clock: NOW,
    persistedKey: null,
    timeouts: [],
    intervals: [],
    downloads: [],
    window: new EventTarget(),
    document: { title: "Platine", documentElement: { lang: "" } },
    history: {
      urls: [],
      replaceState(_state, _title, url) {
        this.urls.push(url);
      },
    },
    location: {
      search,
      pathname: "/",
      origin: "https://platine.example",
      reloads: 0,
      reload() {
        this.reloads++;
      },
    },
  };
  fake.env = {
    fetch,
    i18n,
    window: fake.window,
    document: fake.document,
    history: fake.history,
    location: fake.location,
    navigator: { onLine: true },
    persist(initial, key) {
      fake.persistedKey = key;
      return groups.length ? groups : initial;
    },
    createWorkbox: serviceWorker
      ? (url) => {
          workbox.url = url;
          return workbox;
        }
      : null,
    setTimeout: (callback, ms) => fake.timeouts.push({ callback, ms }),
    setInterval: (callback, ms) => fake.intervals.push({ callback, ms }),
    now: () => fake.clock,
    download: (url) => fake.downloads.push(url),
  };
  return fake;
}

/** Builds the component the way Alpine does, with the `$watch` and `$refs` magics. */
export function mount(env) {
  const component = createPlatine(env);
  const watchers = {};
  component.$watch = (expression, callback) => (watchers[expression] = callback);
  component.$refs = {
    input: {
      focused: 0,
      focus() {
        this.focused++;
      },
    },
  };
  return { component, watchers };
}

/** Lets pending promises (fake network calls) settle. */
export const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
