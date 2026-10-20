// The Platine Alpine component, driven like Alpine would, against a fake browser and server.
import assert from "node:assert/strict";
import { ApiError, createApi, createPlatine } from "../../platine/static/js/component.js";
import { errorResponse, fakeEnv, flush, job, jsonResponse, mount, NNBSP, NOW } from "./helpers.js";

const created = (jobs, playlist = null) => jsonResponse({ playlist, jobs }, 201);
const done = (fields = {}) => job({ status: "done", expires_at: NOW / 1000 + 3600, size: 1000, ...fields });

// ---------------------------------------------------------------------------------------
// API client

Deno.test("createApi returns JSON, null for 204, and ApiErrors with the server code", async () => {
  const request = createApi(async (path) => {
    if (path === "/ok") return jsonResponse({ ok: true });
    if (path === "/empty") return { ok: true, status: 204, json: async () => assert.fail("no body for 204") };
    if (path === "/coded") return errorResponse("queue_full", "Too many conversions are waiting.", 429);
    if (path === "/list") return jsonResponse({ detail: [{ msg: "field required" }] }, 422);
    if (path === "/html") return { ok: false, status: 502, json: async () => JSON.parse("<html>") };
    throw new TypeError("Failed to fetch");
  });

  assert.deepEqual(await request("/ok"), { ok: true });
  assert.equal(await request("/empty"), null);
  await assert.rejects(request("/coded"), (err) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.code, "queue_full");
    assert.equal(err.serverMessage, "Too many conversions are waiting.");
    assert.equal(err.message, "Too many conversions are waiting.");
    return true;
  });
  await assert.rejects(request("/list"), { code: "server", values: { status: 422 } });
  await assert.rejects(request("/html"), { code: "server", values: { status: 502 } });
  await assert.rejects(request("/down"), { code: "network", message: "network", serverMessage: "" });
});

Deno.test("createApi sends JSON headers", async () => {
  let seen;
  const request = createApi(async (path, options) => {
    seen = options;
    return jsonResponse({});
  });
  await request("/api/jobs", { method: "POST", body: "{}" });
  assert.deepEqual(seen, { headers: { "Content-Type": "application/json" }, method: "POST", body: "{}" });
});

// ---------------------------------------------------------------------------------------
// Start-up

Deno.test("init restores the list, reads the config, polls and follows the title", async () => {
  const fake = await fakeEnv({
    groups: [{ id: "g", playlist: null, jobs: [job({ id: "a", status: "downloading", autoSave: true })] }],
    routes: {
      "GET /api/config": jsonResponse({ file_ttl: 900, max_playlist_items: 100 }),
      "GET /api/jobs": jsonResponse([job({ id: "a", status: "converting" })]),
    },
  });
  const { component, watchers } = mount(fake.env);
  assert.equal(fake.persistedKey, "platine:groups");

  component.init();
  await flush();

  assert.equal(component.groups[0].jobs[0].autoSave, false); // no surprise download after a reload
  assert.equal(component.groups[0].jobs[0].status, "converting");
  assert.equal(component.fileTtl, 900);
  assert.equal(fake.document.documentElement.lang, "en");
  assert.equal(fake.timeouts.at(-1).ms, 700); // something is still converting
  assert.deepEqual(fake.history.urls, []);

  watchers.activeCount(2);
  assert.equal(fake.document.title, "(2) Platine");
  watchers.activeCount(0);
  assert.equal(fake.document.title, "Platine");

  assert.equal(fake.intervals[0].ms, 15_000);
  fake.clock += 60_000;
  fake.intervals[0].callback();
  assert.equal(component.now, NOW + 60_000);
});

Deno.test("init survives a missing config and an empty list", async () => {
  const fake = await fakeEnv({ routes: { "GET /api/config": new TypeError("offline") } });
  const { component } = mount(fake.env);
  component.init();
  await flush();
  assert.equal(component.fileTtl, 3600);
  assert.equal(fake.calls.filter((c) => c.path.startsWith("/api/jobs")).length, 0);
  assert.equal(fake.timeouts.at(-1).ms, 2000); // idle polling
});

Deno.test("a link shared through ?url= or ?text= starts converting right away", async () => {
  for (const search of ["?url=https%3A%2F%2Fyoutu.be%2Fx", "?text=Listen%20https%3A%2F%2Fyoutu.be%2Fx"]) {
    const fake = await fakeEnv({ search, routes: { "POST /api/jobs": created([job({ id: "n" })]) } });
    const { component } = mount(fake.env);
    component.init();
    await flush();
    assert.deepEqual(fake.history.urls, ["/"]);
    assert.deepEqual(fake.calls.find((c) => c.method === "POST").body, { url: "https://youtu.be/x" });
    assert.equal(component.groups[0].jobs[0].autoSave, true);
  }
});

Deno.test("the language comes from i18next, with English as the fallback", async () => {
  const french = await fakeEnv({ lng: "fr" });
  assert.equal(createPlatine(french.env).lang, "fr");

  const unknown = await fakeEnv();
  unknown.env.i18n = Object.create(unknown.i18n, { resolvedLanguage: { value: undefined } });
  assert.equal(createPlatine(unknown.env).lang, "en");
});

// ---------------------------------------------------------------------------------------
// Language

Deno.test("setLanguage switches every text and remembers the choice", async () => {
  const fake = await fakeEnv();
  const { component } = mount(fake.env);
  assert.equal(component.t("hero.title"), "Paste a link.");
  assert.equal(component.ttlLabel, "1 hour");

  component.setLanguage("fr");
  await flush();
  assert.equal(component.lang, "fr");
  assert.equal(fake.document.documentElement.lang, "fr");
  assert.equal(fake.i18n.language, "fr");
  assert.equal(component.t("hero.title"), "Colle un lien.");
  assert.equal(component.t("footer.about", { ttl: component.ttlLabel }).includes(`1${NNBSP}h`), true);
  assert.equal(component.errorText({ code: "empty_input" }), "Colle d'abord un lien.");
  assert.deepEqual(component.languages.map((l) => l.code), ["fr", "en"]);
});

// ---------------------------------------------------------------------------------------
// Installable app

Deno.test("PWA: offline notice, install prompt and update", async () => {
  const fake = await fakeEnv();
  const { component } = mount(fake.env);
  component.setUpApp();
  assert.equal(fake.workbox.url, "/sw.js");
  assert.equal(fake.workbox.registered, true);

  fake.window.dispatchEvent(new Event("offline"));
  assert.equal(component.online, false);
  fake.window.dispatchEvent(new Event("online"));
  assert.equal(component.online, true);

  await component.install(); // nothing to install yet
  const prompt = Object.assign(new Event("beforeinstallprompt", { cancelable: true }), {
    prompted: 0,
    prompt() {
      this.prompted++;
    },
    userChoice: Promise.resolve({ outcome: "accepted" }),
  });
  fake.window.dispatchEvent(prompt);
  assert.equal(prompt.defaultPrevented, true);
  assert.equal(component.canInstall, true);
  await component.install();
  assert.equal(prompt.prompted, 1);
  assert.equal(component.canInstall, false);
  await component.install(); // the prompt can only be used once
  assert.equal(prompt.prompted, 1);

  fake.window.dispatchEvent(prompt);
  fake.window.dispatchEvent(new Event("appinstalled"));
  assert.equal(component.canInstall, false);

  fake.workbox.emit("waiting");
  assert.equal(component.updateReady, true);
  component.applyUpdate();
  assert.equal(fake.workbox.skippedWaiting, true);
  fake.workbox.emit("controlling");
  assert.equal(fake.location.reloads, 1);
});

Deno.test("PWA: without service workers, nothing is registered", async () => {
  const fake = await fakeEnv({ serviceWorker: false });
  const { component } = mount(fake.env);
  component.setUpApp();
  component.applyUpdate();
  assert.equal(fake.location.reloads, 0);
});

// ---------------------------------------------------------------------------------------
// Input

function clipboard(text) {
  return {
    prevented: false,
    preventDefault() {
      this.prevented = true;
    },
    clipboardData: { getData: () => text },
  };
}

Deno.test("pasting a link into the empty field converts it", async () => {
  const fake = await fakeEnv({ routes: { "POST /api/jobs": created([job({ id: "n" })]) } });
  const { component } = mount(fake.env);

  const paste = clipboard("https://youtu.be/x");
  component.onPaste(paste);
  await flush();
  assert.equal(paste.prevented, true);
  assert.equal(component.groups.length, 1);

  component.url = "already typed";
  const other = clipboard("https://youtu.be/y");
  component.onPaste(other);
  assert.equal(other.prevented, false); // normal paste into what the user is typing

  component.url = "";
  const words = clipboard("no link");
  component.onPaste(words);
  assert.equal(words.prevented, false);
  component.onPaste({ preventDefault: () => assert.fail("nothing pasted") });
});

Deno.test("dropping a link converts it", async () => {
  const fake = await fakeEnv({ routes: { "POST /api/jobs": created([job({ id: "n" })]) } });
  const { component } = mount(fake.env);
  const drop = (types) => ({ dataTransfer: { getData: (type) => types[type] ?? "" } });

  component.dragging = true;
  component.onDrop(drop({ "text/uri-list": "https://youtu.be/x" }));
  assert.equal(component.dragging, false);
  component.onDrop(drop({ "text/plain": "https://soundcloud.com/y" }));
  component.onDrop(drop({ "text/plain": "nothing" }));
  await flush();
  assert.deepEqual(fake.calls.map((c) => c.body.url), ["https://youtu.be/x", "https://soundcloud.com/y"]);
});

Deno.test("submit converts, or explains what is wrong", async () => {
  const fake = await fakeEnv({ routes: { "POST /api/jobs": created([job({ id: "n" })]) } });
  const { component } = mount(fake.env);

  component.submit();
  assert.deepEqual(component.error, { code: "empty_input" });
  assert.equal(component.errorText(component.error), "Paste a link first.");
  assert.equal(component.$refs.input.focused, 1);

  component.url = "never gonna give you up";
  component.submit();
  assert.deepEqual(component.error, { code: "not_a_link" });

  component.url = "https://youtu.be/x";
  await component.submit();
  assert.equal(component.error, null);
  assert.equal(component.url, "");
  assert.equal(component.pending, 0);
});

// ---------------------------------------------------------------------------------------
// Converting

Deno.test("convert: a single link saves itself, playlists and batches do not", async () => {
  const fake = await fakeEnv({
    routes: {
      "POST /api/jobs": (_path, options) =>
        JSON.parse(options.body).url.includes("album")
          ? created([job({ id: "a1" }), job({ id: "a2" })], "Discovery")
          : created([job({ id: JSON.parse(options.body).url.slice(-1) })]),
    },
  });
  const { component } = mount(fake.env);

  await component.convert(["https://youtu.be/x"]);
  await component.convert(["https://open.spotify.com/album/1"]);
  await component.convert(["https://youtu.be/y", "https://youtu.be/z"]);

  assert.deepEqual(component.groups.map((g) => [g.id, g.playlist, g.jobs.map((j) => j.autoSave)]), [
    ["z", null, [false]],
    ["y", null, [false]],
    ["a1", "Discovery", [false, false]],
    ["x", null, [true]],
  ]);
});

Deno.test("convert: errors are kept as codes and the link is given back", async () => {
  const fake = await fakeEnv({
    routes: { "POST /api/jobs": errorResponse("unsupported_site", "This site is not supported.") },
  });
  const { component } = mount(fake.env);
  await component.convert(["https://example.com/"]);
  assert.deepEqual(component.error, { code: "unsupported_site", message: "This site is not supported.", values: undefined });
  assert.equal(component.url, "https://example.com/");
  assert.equal(component.errorText(component.error), "This site is not supported, or the page has no audio or video.");
  component.setLanguage("fr");
  assert.equal(component.errorText(component.error), "Ce site n'est pas pris en charge, ou la page ne contient ni son ni vidéo.");
});

Deno.test("convert: a broken answer becomes an unexpected error", async () => {
  const fake = await fakeEnv({ routes: { "POST /api/jobs": jsonResponse({ playlist: null }, 201) } });
  const { component } = mount(fake.env);
  await component.convert(["https://youtu.be/x"]);
  assert.deepEqual(component.error, { code: "unexpected" });
  assert.equal(component.pending, 0);
});

// ---------------------------------------------------------------------------------------
// Following conversions

Deno.test("refresh updates active jobs and saves finished single downloads", async () => {
  const fake = await fakeEnv({
    groups: [
      {
        id: "g",
        jobs: [
          job({ id: "a", status: "converting", autoSave: true }),
          job({ id: "b", status: "downloading", autoSave: false }),
          job({ id: "c", status: "downloading" }),
          job({ id: "d", status: "queued" }),
          done({ id: "e", autoSave: true }),
        ],
      },
    ],
    routes: {
      "GET /api/jobs": jsonResponse([
        done({ id: "a" }),
        done({ id: "b" }),
        job({ id: "c", status: "downloading", progress: 0.5 }),
        done({ id: "e" }),
      ]),
    },
  });
  const { component } = mount(fake.env);

  await component.refresh();
  const [a, b, c, d, e] = component.groups[0].jobs;
  assert.deepEqual(fake.calls[0].path, "/api/jobs?ids=a,b,c,d");
  assert.deepEqual([a.status, b.status, c.progress, d.status], ["done", "done", 0.5, "expired"]);
  assert.deepEqual(fake.downloads, ["/api/jobs/a/file"]);
  assert.equal(a.autoSave, false);
  assert.equal(e.autoSave, true); // was already done: not refreshed, not downloaded again

  await component.refresh(true); // a full refresh also checks finished files
  assert.equal(fake.calls[1].path, "/api/jobs?ids=a,b,c,e");
  assert.deepEqual(fake.downloads, ["/api/jobs/a/file"]);
});

Deno.test("refresh: forgotten jobs expire, unless they already failed", async () => {
  const fake = await fakeEnv({
    groups: [{ id: "g", jobs: [job({ id: "x", status: "error" }), job({ id: "y", status: "cancelled" }), done({ id: "z" })] }],
    routes: { "GET /api/jobs": jsonResponse([]) },
  });
  const { component } = mount(fake.env);
  await component.refresh(true);
  assert.deepEqual(component.jobs.map((j) => j.status), ["error", "cancelled", "expired"]);
});

Deno.test("refresh: an unreachable server changes nothing", async () => {
  const fake = await fakeEnv({
    groups: [{ id: "g", jobs: [job({ id: "a", status: "downloading" })] }],
    routes: { "GET /api/jobs": new TypeError("Failed to fetch") },
  });
  const { component } = mount(fake.env);
  await component.refresh();
  assert.equal(component.jobs[0].status, "downloading");
});

Deno.test("poll keeps going, faster while something converts", async () => {
  const fake = await fakeEnv({
    groups: [{ id: "g", jobs: [job({ id: "a", status: "downloading" })] }],
    routes: { "GET /api/jobs": jsonResponse([done({ id: "a" })]) },
  });
  const { component } = mount(fake.env);
  await component.poll();
  assert.equal(fake.timeouts[0].ms, 2000); // the job just finished
  await fake.timeouts[0].callback();
  assert.equal(fake.timeouts.length, 2);
});

// ---------------------------------------------------------------------------------------
// Actions

Deno.test("cancel asks the server, and falls back to cancelled", async () => {
  const fake = await fakeEnv({
    routes: {
      "POST /api/jobs/a/cancel": jsonResponse(job({ id: "a", status: "cancelled", error: null })),
      "POST /api/jobs/b/cancel": new TypeError("Failed to fetch"),
    },
  });
  const { component } = mount(fake.env);
  const a = job({ id: "a", status: "downloading" });
  const b = job({ id: "b", status: "downloading" });
  await component.cancel(a);
  await component.cancel(b);
  assert.deepEqual([a.status, b.status], ["cancelled", "cancelled"]);
});

Deno.test("remove forgets a job, and its group once empty", async () => {
  const fake = await fakeEnv({
    groups: [{ id: "g", jobs: [done({ id: "a" }), done({ id: "b" })] }],
    routes: { "DELETE /api/jobs/a": { ok: true, status: 204 }, "DELETE /api/jobs/b": new TypeError("offline") },
  });
  const { component } = mount(fake.env);
  const [group] = component.groups;
  component.remove(group, group.jobs[0]);
  assert.deepEqual(component.groups[0].jobs.map((j) => j.id), ["b"]);
  component.remove(group, group.jobs[0]);
  await flush();
  assert.deepEqual(component.groups, []);
  assert.deepEqual(fake.calls.map((c) => `${c.method} ${c.path}`), ["DELETE /api/jobs/a", "DELETE /api/jobs/b"]);
});

Deno.test("retry replaces the job, or shows why it failed again", async () => {
  let attempt = 0;
  const fake = await fakeEnv({
    routes: {
      "POST /api/jobs": () =>
        ++attempt === 1 ? created([job({ id: "new" })]) : errorResponse("ytm_no_match", "Track not found on YouTube Music."),
    },
  });
  const { component } = mount(fake.env);
  const group = { id: "g", jobs: [job({ id: "old", status: "error", url: "https://open.spotify.com/track/1" })] };

  await component.retry(group, group.jobs[0]);
  assert.deepEqual(group.jobs.map((j) => [j.id, j.autoSave]), [["new", false]]);
  assert.deepEqual(fake.calls[0].body, { url: "https://open.spotify.com/track/1" });

  const failed = group.jobs[0];
  await component.retry(group, failed);
  assert.equal(failed.status, "error");
  assert.equal(component.statusText(failed), "Track not found on YouTube Music.");
});

Deno.test("clearFinished keeps only what is still converting", async () => {
  const fake = await fakeEnv({
    groups: [
      { id: "g1", jobs: [done({ id: "a" }), job({ id: "b", status: "downloading" })] },
      { id: "g2", jobs: [job({ id: "c", status: "error" })] },
    ],
    routes: { "DELETE /api/jobs/a": { ok: true, status: 204 }, "DELETE /api/jobs/c": { ok: true, status: 204 } },
  });
  const { component } = mount(fake.env);
  assert.equal(component.hasFinished, true);
  component.clearFinished();
  await flush();
  assert.deepEqual(component.groups.map((g) => [g.id, g.jobs.map((j) => j.id)]), [["g1", ["b"]]]);
  assert.equal(component.hasFinished, false);
  assert.deepEqual(fake.calls.map((c) => c.path).sort(), ["/api/jobs/a", "/api/jobs/c"]);
});

// ---------------------------------------------------------------------------------------
// Display

Deno.test("display helpers use the current language and clock", async () => {
  const fake = await fakeEnv();
  const { component } = mount(fake.env);
  const finished = done({ id: "a", source: "Spotify", artist: "Daft Punk", duration: 320 });
  const group = { playlist: "Discovery", jobs: [finished, done({ id: "b" })] };

  assert.equal(component.state(finished), "done");
  assert.equal(component.isActive(finished), false);
  assert.equal(component.statusText(finished), "Ready, 1 kB");
  assert.match(component.detailText(finished), /^until /);
  assert.equal(component.subtitle(finished), "Daft Punk, 5:20");
  assert.equal(component.sourceIcon(finished), "bi-spotify");
  assert.equal(component.sourceLabel(finished), "Spotify, audio from YouTube Music");
  assert.equal(component.ringOffset(finished), 0);
  assert.equal(component.fileUrl(finished), "/api/jobs/a/file");
  assert.deepEqual(component.readyIds(group), ["a", "b"]);
  assert.equal(component.archiveUrl(group), "/api/archive?ids=a,b&name=Discovery");
  assert.equal(component.groupSummary(group), "2 tracks, all ready");
  assert.equal(component.bookmarklet.startsWith("javascript:location.href='https://platine.example/?url='"), true);

  component.now = NOW + 2 * 3600 * 1000;
  assert.equal(component.state(finished), "expired");
  component.setLanguage("fr");
  assert.equal(component.groupSummary(group), "2 morceaux, 0 prêt");
});

Deno.test("nowPlaying shows the cover of the track really in progress", async () => {
  const fake = await fakeEnv();
  const { component } = mount(fake.env);
  assert.equal(component.nowPlaying, null);
  component.groups.push({
    id: "g",
    jobs: [
      job({ id: "q", status: "queued", thumbnail: "q.jpg" }),
      job({ id: "n", status: "downloading" }),
      job({ id: "d", status: "downloading", thumbnail: "d.jpg" }),
    ],
  });
  assert.equal(component.nowPlaying.id, "d");
  component.groups[0].jobs[2].status = "done";
  assert.equal(component.nowPlaying.id, "q"); // nothing running has a cover: the next one
  assert.equal(component.activeCount, 2);
});
