// Display rules of the interface, in both languages: `deno test tests/js`.
import assert from "node:assert/strict";
import * as lib from "../../platine/static/js/lib.js";
import { context, job, NNBSP, NOW } from "./helpers.js";

const en = await context("en");
const fr = await context("fr");

Deno.test("findUrls finds one or several links in pasted text", () => {
  assert.deepEqual(lib.findUrls("https://youtu.be/x"), ["https://youtu.be/x"]);
  assert.deepEqual(
    lib.findUrls("Listen: https://youtu.be/a\nhttps://soundcloud.com/b and spotify:track:c"),
    ["https://youtu.be/a", "https://soundcloud.com/b", "spotify:track:c"],
  );
  assert.deepEqual(lib.findUrls("no link here"), []);
  assert.deepEqual(lib.findUrls(undefined), []);
});

Deno.test("formatBytes uses each language's units and separators", () => {
  assert.equal(lib.formatBytes(null, en), "");
  assert.equal(lib.formatBytes(512, en), "512 B");
  assert.equal(lib.formatBytes(7_400_000, en), "7.4 MB");
  assert.equal(lib.formatBytes(7_400_000, fr), `7,4${NNBSP}Mo`);
  assert.equal(lib.formatBytes(2_000_000_000, fr), `2${NNBSP}Go`);
  assert.equal(lib.formatBytes(3_000_000_000_000, en), "3,000 GB"); // no unit past GB
});

Deno.test("formatPercent rounds down and never goes past 100", () => {
  assert.equal(lib.formatPercent(0.429, en), "42%");
  assert.equal(lib.formatPercent(0.429, fr), `42${NNBSP}%`);
  assert.equal(lib.formatPercent(1.3, en), "100%");
});

Deno.test("formatDuration", () => {
  assert.equal(lib.formatDuration(null), "");
  assert.equal(lib.formatDuration(65.4), "1:05");
  assert.equal(lib.formatDuration(3725), "1:02:05");
});

Deno.test("formatTtl speaks in hours or minutes", () => {
  assert.equal(lib.formatTtl(3600, en), "1 hour");
  assert.equal(lib.formatTtl(5400, en), "1.5 hours");
  assert.equal(lib.formatTtl(60, en), "1 minute");
  assert.equal(lib.formatTtl(900, en), "15 minutes");
  assert.equal(lib.formatTtl(3600, fr), `1${NNBSP}h`);
  assert.equal(lib.formatTtl(5400, fr), `1,5${NNBSP}h`);
  assert.equal(lib.formatTtl(900, fr), `15${NNBSP}min`);
});

Deno.test("formatTime follows the language's clock", () => {
  assert.match(lib.formatTime(NOW, "en"), /^\d{1,2}:\d{2}\s[AP]M$/u);
  assert.match(lib.formatTime(NOW, "fr"), /^\d{2}:\d{2}$/);
});

Deno.test("errorText translates server codes and keeps unknown messages", () => {
  assert.equal(lib.errorText(null, en), "");
  assert.equal(lib.errorText("Saved by an older version.", en), "Saved by an older version.");
  assert.equal(lib.errorText({ code: "drm", message: "ignored" }, en), "This media is DRM-protected and cannot be downloaded.");
  assert.equal(lib.errorText({ code: "drm" }, fr), `Ce média est protégé par DRM${NNBSP}: impossible de le récupérer.`);
  assert.equal(lib.errorText({ code: "server", values: { status: 502 } }, fr), "Le serveur a répondu 502.");
  assert.equal(lib.errorText({ code: "download_failed", message: "[foo] bar: weird" }, fr), "[foo] bar: weird");
  assert.equal(lib.errorText({ code: "brand_new_code" }, en), "Unexpected error during the conversion.");
});

Deno.test("a finished file turns expired once its time is up", () => {
  const done = job({ status: "done", expires_at: NOW / 1000 + 60, size: 7_400_000 });
  assert.equal(lib.jobState(done, NOW), "done");
  assert.equal(lib.jobState(done, NOW + 61_000), "expired");
  assert.equal(lib.jobState(job({ status: "done" }), NOW), "done"); // no expiry known
  assert.equal(lib.statusText(done, NOW, en), "Ready, 7.4 MB");
  assert.equal(lib.statusText(done, NOW, fr), `Prêt, 7,4${NNBSP}Mo`);
  assert.match(lib.detailText(done, NOW, en), /^until \d{1,2}:\d{2}\s[AP]M$/u);
  assert.match(lib.detailText(done, NOW, fr), /^jusqu'à \d{2}:\d{2}$/);
  assert.equal(lib.statusText(done, NOW + 61_000, en), "File expired: start the conversion again");
  assert.equal(lib.statusText(done, NOW + 61_000, fr), `Fichier expiré${NNBSP}: relance la conversion`);
});

Deno.test("statusText describes every step", () => {
  const cases = [
    [job(), "Waiting", "En attente"],
    [job({ status: "matching" }), "Searching YouTube Music", "Recherche sur YouTube Music"],
    [job({ status: "downloading" }), "Downloading", "Téléchargement"],
    [job({ status: "downloading", progress: 0.42 }), "Downloading 42%", `Téléchargement 42${NNBSP}%`],
    [job({ status: "converting" }), "Converting to MP3 320 kbps", "Conversion en MP3 320 kbps"],
    [job({ status: "done" }), "Ready", "Prêt"],
    [job({ status: "error", error: { code: "private" } }), "This video is private.", "Cette vidéo est privée."],
    [job({ status: "error" }), "The conversion failed.", "La conversion a échoué."],
    [job({ status: "cancelled" }), "Cancelled", "Annulé"],
    [job({ status: "unknown" }), "", ""],
  ];
  for (const [item, english, french] of cases) {
    assert.equal(lib.statusText(item, NOW, en), english);
    assert.equal(lib.statusText(item, NOW, fr), french);
  }
});

Deno.test("detailText shows the speed while downloading", () => {
  assert.equal(lib.detailText(job({ status: "downloading", speed: 1_250_000 }), NOW, en), "1.3 MB/s");
  assert.equal(lib.detailText(job({ status: "downloading", speed: 1_250_000 }), NOW, fr), `1,3${NNBSP}Mo/s`);
  assert.equal(lib.detailText(job({ status: "downloading" }), NOW, en), "");
  assert.equal(lib.detailText(job({ status: "done" }), NOW, en), "");
  assert.equal(lib.detailText(job(), NOW, en), "");
});

Deno.test("ringOffset follows the progress", () => {
  assert.equal(lib.ringOffset(job(), NOW), 100);
  assert.equal(lib.ringOffset(job({ status: "downloading" }), NOW), 100);
  assert.equal(lib.ringOffset(job({ status: "downloading", progress: 0.25 }), NOW), 75);
  assert.equal(lib.ringOffset(job({ status: "downloading", progress: 1.2 }), NOW), 0);
  assert.equal(lib.ringOffset(job({ status: "done" }), NOW), 0);
});

Deno.test("sources: Bootstrap icon and label", () => {
  assert.equal(lib.sourceIcon({ source: "Spotify" }), "bi-spotify");
  assert.equal(lib.sourceIcon({ source: "radiofrance.fr" }), "bi-globe2");
  assert.equal(lib.sourceLabel({ source: "Spotify" }, en), "Spotify, audio from YouTube Music");
  assert.equal(lib.sourceLabel({ source: "Spotify" }, fr), "Spotify, son récupéré sur YouTube Music");
  assert.equal(lib.sourceLabel({ source: "YouTube" }, fr), "YouTube");
  assert.equal(lib.subtitle({ artist: "Daft Punk", album: "Discovery", duration: 320 }), "Daft Punk, Discovery, 5:20");
  assert.equal(lib.subtitle({}), "");
  assert.equal(lib.isActive(job({ status: "converting" })), true);
  assert.equal(lib.isActive(job({ status: "done" })), false);
});

Deno.test("groups: summary and archive of the finished tracks", () => {
  const group = {
    playlist: "Discovery",
    jobs: [job({ id: "a", status: "done" }), job({ id: "b", status: "done" }), job({ id: "c", status: "downloading" })],
  };
  assert.deepEqual(lib.readyIds(group, NOW), ["a", "b"]);
  assert.equal(lib.archiveUrl(group, NOW), "/api/archive?ids=a,b&name=Discovery");
  assert.equal(lib.archiveUrl({ jobs: [] }, NOW), "/api/archive?ids=&name=Platine");
  assert.equal(lib.groupSummary(group, NOW, en), "3 tracks, 2 ready");
  assert.equal(lib.groupSummary(group, NOW, fr), "3 morceaux, 2 prêts");

  const single = { jobs: [job({ status: "done" })] };
  assert.equal(lib.groupSummary(single, NOW, en), "1 track, ready");
  assert.equal(lib.groupSummary(single, NOW, fr), "1 morceau, prêt");
  const pair = { jobs: [job({ status: "done" }), job({ status: "done" })] };
  assert.equal(lib.groupSummary(pair, NOW, en), "2 tracks, all ready");
  assert.equal(lib.groupSummary(pair, NOW, fr), "2 morceaux, tous prêts");
  const none = { jobs: [job()] };
  assert.equal(lib.groupSummary(none, NOW, en), "1 track, 0 ready");
  assert.equal(lib.groupSummary(none, NOW, fr), "1 morceau, 0 prêt");
});

Deno.test("bookmarklet", () => {
  assert.equal(
    lib.bookmarklet("http://localhost:8320"),
    "javascript:location.href='http://localhost:8320/?url='+encodeURIComponent(location.href)",
  );
});
