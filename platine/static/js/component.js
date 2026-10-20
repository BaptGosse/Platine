// The Platine Alpine component. It is built by a factory so that every browser dependency
// (network, storage, i18n, timers, PWA hooks) comes from `env` and can be replaced in tests.
// main.js gives it the real browser objects.

import { LANGUAGES } from "./i18n.js";
import * as lib from "./lib.js";

const POLL_ACTIVE_MS = 700;
const POLL_IDLE_MS = 2000;
const CLOCK_MS = 15_000;

/** An error the interface knows how to translate: a server code or one of its own. */
export class ApiError extends Error {
  constructor(code, message = "", values = undefined) {
    super(message || code);
    this.code = code;
    this.serverMessage = message;
    this.values = values;
  }
}

/** Error as stored in the component state, so it is translated again when the language changes. */
function errorState(err) {
  if (err instanceof ApiError) return { code: err.code, message: err.serverMessage, values: err.values };
  return { code: "unexpected" };
}

/** JSON client for the Platine API. Errors become `ApiError`s carrying the server's error code. */
export function createApi(fetch) {
  return async function request(path, options = {}) {
    let response;
    try {
      response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
    } catch {
      throw new ApiError("network");
    }
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      const detail = body?.detail;
      // Validation errors (422) carry a list instead of `{ code, message }`.
      if (detail?.code) throw new ApiError(detail.code, detail.message);
      throw new ApiError("server", "", { status: response.status });
    }
    return response.status === 204 ? null : response.json();
  };
}

/**
 * `env` provides: fetch, persist(initial, key), i18n (an i18next instance), window (events),
 * document (title and <html lang>), navigator (onLine), location, history, createWorkbox(url)
 * or null when service workers are unavailable, setTimeout, setInterval, now() and download(url).
 */
export function createPlatine(env) {
  const request = createApi(env.fetch);
  // Browser objects kept out of Alpine's reactive state: its proxies break their native methods.
  let installPrompt = null;
  let workbox = null;

  function forget(job) {
    request(`/api/jobs/${job.id}`, { method: "DELETE" }).catch(() => {});
  }

  return {
    url: "",
    pending: 0,
    error: null,
    groups: env.persist([], "platine:groups"),
    fileTtl: 3600,
    now: env.now(),
    dragging: false,
    online: env.navigator.onLine,
    canInstall: false,
    updateReady: false,
    lang: env.i18n.resolvedLanguage ?? "en",
    languages: LANGUAGES,

    init() {
      // No automatic download for conversions started before the page was reloaded.
      for (const job of this.jobs) job.autoSave = false;
      env.document.documentElement.lang = this.lang;
      request("/api/config")
        .then((config) => (this.fileTtl = config.file_ttl))
        .catch(() => {});
      this.refresh(true).finally(() => this.poll());
      env.setInterval(() => (this.now = env.now()), CLOCK_MS);
      this.$watch("activeCount", (n) => (env.document.title = n ? `(${n}) Platine` : "Platine"));
      this.setUpApp();

      // A link received from the bookmarklet or the Android share sheet (?url=… or ?text=…).
      const params = new URLSearchParams(env.location.search);
      const shared = lib.findUrls(`${params.get("url") ?? ""} ${params.get("text") ?? ""}`);
      if (shared.length) {
        env.history.replaceState(null, "", env.location.pathname);
        this.convert(shared);
      }
    },

    get jobs() {
      return this.groups.flatMap((g) => g.jobs);
    },
    get activeCount() {
      return this.jobs.filter(lib.isActive).length;
    },
    get nowPlaying() {
      // The cover of the track really in progress, otherwise the next one in the queue.
      const withCover = this.jobs.filter((j) => lib.isActive(j) && j.thumbnail);
      return withCover.find((j) => j.status !== "queued") ?? withCover[0] ?? null;
    },
    get hasFinished() {
      return this.jobs.some((j) => !lib.isActive(j));
    },
    get ttlLabel() {
      return lib.formatTtl(this.fileTtl, this.i18n);
    },
    get bookmarklet() {
      return lib.bookmarklet(env.location.origin);
    },

    // Language ---------------------------------------------------------------------

    /** Translation in the current language (reading `lang` keeps Alpine bindings up to date). */
    t(key, options) {
      return env.i18n.t(key, { ...options, lng: this.lang });
    },

    get i18n() {
      return {
        t: (key, options) => this.t(key, options),
        exists: (key) => env.i18n.exists(key, { lng: this.lang }),
        locale: this.lang,
      };
    },

    setLanguage(code) {
      this.lang = code;
      env.document.documentElement.lang = code;
      env.i18n.changeLanguage(code); // the language detector also remembers the choice
    },

    // Installable app (PWA) ----------------------------------------------------------

    setUpApp() {
      env.window.addEventListener("online", () => (this.online = true));
      env.window.addEventListener("offline", () => (this.online = false));
      env.window.addEventListener("beforeinstallprompt", (event) => {
        event.preventDefault(); // the page shows its own "Install the app" button
        installPrompt = event;
        this.canInstall = true;
      });
      env.window.addEventListener("appinstalled", () => (this.canInstall = false));

      // Service workers only exist over HTTPS (or on localhost).
      if (!env.createWorkbox) return;
      workbox = env.createWorkbox("/sw.js");
      workbox.addEventListener("waiting", () => (this.updateReady = true));
      workbox.register();
    },

    async install() {
      if (!installPrompt) return;
      installPrompt.prompt();
      await installPrompt.userChoice;
      installPrompt = null;
      this.canInstall = false;
    },

    applyUpdate() {
      if (!workbox) return;
      workbox.addEventListener("controlling", () => env.location.reload());
      workbox.messageSkipWaiting();
    },

    // Input ------------------------------------------------------------------------

    onPaste(event) {
      const urls = lib.findUrls(event.clipboardData?.getData("text"));
      if (urls.length && !this.url.trim()) {
        event.preventDefault();
        this.convert(urls);
      }
    },

    onDrop(event) {
      this.dragging = false;
      const data = event.dataTransfer;
      const urls = lib.findUrls(data.getData("text/uri-list") || data.getData("text/plain"));
      if (urls.length) this.convert(urls);
    },

    submit() {
      const urls = lib.findUrls(this.url);
      if (urls.length) return this.convert(urls);
      this.error = { code: this.url.trim() ? "not_a_link" : "empty_input" };
      this.$refs.input.focus();
    },

    async convert(urls) {
      this.error = null;
      this.url = "";
      for (const url of urls) {
        this.pending++;
        try {
          const created = await request("/api/jobs", { method: "POST", body: JSON.stringify({ url }) });
          const autoSave = !created.playlist && urls.length === 1;
          this.groups.unshift({
            id: created.jobs[0].id,
            playlist: created.playlist,
            jobs: created.jobs.map((j) => ({ ...j, autoSave })),
          });
        } catch (err) {
          this.error = errorState(err);
          this.url = url;
        } finally {
          this.pending--;
        }
      }
    },

    // Following conversions -------------------------------------------------------

    async refresh(all = false) {
      const targets = this.jobs.filter((j) => (all ? j.status !== "expired" : lib.isActive(j)));
      if (!targets.length) return;
      const fresh = await request(`/api/jobs?ids=${targets.map((j) => j.id).join(",")}`).catch(() => null);
      if (!fresh) return; // server unreachable: try again on the next round
      const byId = new Map(fresh.map((j) => [j.id, j]));
      for (const job of targets) {
        const next = byId.get(job.id);
        if (!next) {
          // The server forgot this conversion (expired file or restart).
          if (job.status !== "error" && job.status !== "cancelled") job.status = "expired";
          continue;
        }
        const justDone = job.status !== "done" && next.status === "done";
        Object.assign(job, next);
        if (justDone && job.autoSave) {
          job.autoSave = false;
          this.download(job);
        }
      }
    },

    async poll() {
      await this.refresh();
      env.setTimeout(() => this.poll(), this.activeCount ? POLL_ACTIVE_MS : POLL_IDLE_MS);
    },

    // Actions ------------------------------------------------------------------------

    download(job) {
      env.download(this.fileUrl(job));
    },

    async cancel(job) {
      try {
        Object.assign(job, await request(`/api/jobs/${job.id}/cancel`, { method: "POST" }));
      } catch {
        job.status = "cancelled";
      }
    },

    remove(group, job) {
      forget(job);
      group.jobs.splice(group.jobs.indexOf(job), 1);
      if (!group.jobs.length) this.groups.splice(this.groups.indexOf(group), 1);
    },

    async retry(group, job) {
      Object.assign(job, { status: "queued", error: null, progress: null });
      try {
        const created = await request("/api/jobs", { method: "POST", body: JSON.stringify({ url: job.url }) });
        const fresh = created.jobs.map((j) => ({ ...j, autoSave: false }));
        group.jobs.splice(group.jobs.indexOf(job), 1, ...fresh);
      } catch (err) {
        Object.assign(job, { status: "error", error: errorState(err) });
      }
    },

    clearFinished() {
      for (const group of this.groups) {
        group.jobs.filter((j) => !lib.isActive(j)).forEach(forget);
        group.jobs = group.jobs.filter(lib.isActive);
      }
      this.groups = this.groups.filter((g) => g.jobs.length);
    },

    // Display (the rules live in lib.js) ------------------------------------------------

    state(job) {
      return lib.jobState(job, this.now);
    },
    isActive: lib.isActive,
    statusText(job) {
      return lib.statusText(job, this.now, this.i18n);
    },
    detailText(job) {
      return lib.detailText(job, this.now, this.i18n);
    },
    errorText(error) {
      return lib.errorText(error, this.i18n);
    },
    subtitle: lib.subtitle,
    sourceIcon: lib.sourceIcon,
    sourceLabel(job) {
      return lib.sourceLabel(job, this.i18n);
    },
    ringOffset(job) {
      return lib.ringOffset(job, this.now);
    },
    fileUrl(job) {
      return `/api/jobs/${job.id}/file`;
    },
    readyIds(group) {
      return lib.readyIds(group, this.now);
    },
    archiveUrl(group) {
      return lib.archiveUrl(group, this.now);
    },
    groupSummary(group) {
      return lib.groupSummary(group, this.now, this.i18n);
    },
  };
}
