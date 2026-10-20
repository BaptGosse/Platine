// Pure helpers for the interface: formatting and display rules for conversions.
// No DOM access, so they run in `deno test tests/js`.
//
// Functions that produce text take an `i18n` context: `{ t, exists, locale }`, where `t` and
// `exists` are bound to the current language and `locale` is its code ("en", "fr").

export const ACTIVE = new Set(["queued", "matching", "downloading", "converting"]);

const SOURCE_ICONS = {
  "YouTube": "bi-youtube",
  "YouTube Music": "bi-youtube",
  "Spotify": "bi-spotify",
  "SoundCloud": "bi-soundwave",
  "Bandcamp": "bi-vinyl-fill",
  "Mixcloud": "bi-cloud-fill",
  "Vimeo": "bi-vimeo",
  "Twitch": "bi-twitch",
  "TikTok": "bi-tiktok",
  "Instagram": "bi-instagram",
  "Facebook": "bi-facebook",
  "X": "bi-twitter-x",
  "Reddit": "bi-reddit",
};

// States whose text does not depend on the job's data.
const STATUS_KEYS = {
  queued: "status.queued",
  matching: "status.matching",
  converting: "status.converting",
  cancelled: "status.cancelled",
  expired: "status.expired",
};

const SIZE_UNITS = ["B", "kB", "MB", "GB"];
const decimalFormats = new Map();

function decimal(locale) {
  if (!decimalFormats.has(locale)) {
    decimalFormats.set(locale, new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }));
  }
  return decimalFormats.get(locale);
}

/** Links found in pasted or shared text (there can be several, one per line for instance). */
export function findUrls(text) {
  return (text ?? "").match(/(?:https?:\/\/|spotify:)[^\s<>"]+/g) ?? [];
}

export function formatBytes(bytes, i18n) {
  if (bytes == null) return "";
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < SIZE_UNITS.length - 1) {
    value /= 1000;
    unit++;
  }
  return i18n.t("units.size", { value: decimal(i18n.locale).format(value), unit: i18n.t(`units.${SIZE_UNITS[unit]}`) });
}

export function formatPercent(fraction, i18n) {
  // Rounded down: 100 % only shows once the download is really over.
  return i18n.t("units.percent", { value: Math.floor(Math.min(fraction, 1) * 100) });
}

export function formatDuration(seconds) {
  if (!seconds) return "";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export function formatTtl(seconds, i18n) {
  const minutes = Math.round(seconds / 60);
  const [key, count] = minutes >= 60 ? ["units.hours", minutes / 60] : ["units.minutes", minutes];
  return i18n.t(key, { count, value: decimal(i18n.locale).format(count) });
}

export function formatTime(timestamp, locale) {
  return new Intl.DateTimeFormat(locale, { hour: "numeric", minute: "2-digit" }).format(timestamp);
}

/** Text for an error coming from the server (`{ code, message }`) or raised by the interface. */
export function errorText(error, i18n) {
  if (!error) return "";
  if (typeof error === "string") return error; // lists saved before errors had codes
  const key = `errors.${error.code}`;
  if (i18n.exists(key)) return i18n.t(key, error.values);
  // Unknown code (a raw yt-dlp message for instance): the server's English message.
  return error.message || i18n.t("errors.unexpected");
}

/** Displayed state: the server's, except for a finished file whose time is up. */
export function jobState(job, now) {
  const expired = job.status === "done" && job.expires_at && job.expires_at * 1000 < now;
  return expired ? "expired" : job.status;
}

export function isActive(job) {
  return ACTIVE.has(job.status);
}

export function statusText(job, now, i18n) {
  const state = jobState(job, now);
  if (state in STATUS_KEYS) return i18n.t(STATUS_KEYS[state]);
  if (state === "downloading") {
    if (job.progress == null) return i18n.t("status.downloading");
    return i18n.t("status.downloadingPercent", { percent: formatPercent(job.progress, i18n) });
  }
  if (state === "done") {
    return job.size ? i18n.t("status.doneSize", { size: formatBytes(job.size, i18n) }) : i18n.t("status.done");
  }
  if (state === "error") return job.error ? errorText(job.error, i18n) : i18n.t("status.failed");
  return "";
}

export function detailText(job, now, i18n) {
  const state = jobState(job, now);
  if (state === "downloading" && job.speed) {
    return i18n.t("detail.speed", { speed: formatBytes(job.speed, i18n) });
  }
  if (state === "done" && job.expires_at) {
    return i18n.t("detail.until", { time: formatTime(job.expires_at * 1000, i18n.locale) });
  }
  return "";
}

export function subtitle(job) {
  return [job.artist, job.album, formatDuration(job.duration)].filter(Boolean).join(", ");
}

export function sourceIcon(job) {
  return SOURCE_ICONS[job.source] ?? "bi-globe2";
}

export function sourceLabel(job, i18n) {
  return job.source === "Spotify" ? i18n.t("track.spotifySource") : job.source;
}

/** Stroke offset of the progress ring (a circle whose length is 100). */
export function ringOffset(job, now) {
  const state = jobState(job, now);
  if (state === "done") return 0;
  if (state === "downloading" && job.progress != null) return 100 * (1 - Math.min(job.progress, 1));
  return 100;
}

export function readyIds(group, now) {
  return group.jobs.filter((j) => jobState(j, now) === "done").map((j) => j.id);
}

export function archiveUrl(group, now) {
  const name = encodeURIComponent(group.playlist ?? "Platine");
  return `/api/archive?ids=${readyIds(group, now).join(",")}&name=${name}`;
}

export function groupSummary(group, now, i18n) {
  const total = group.jobs.length;
  const ready = readyIds(group, now).length;
  return i18n.t("group.summary", {
    tracks: i18n.t("group.tracks", { count: total }),
    ready: ready === total ? i18n.t("group.allReady", { count: total }) : i18n.t("group.ready", { count: ready }),
  });
}

export function bookmarklet(origin) {
  return `javascript:location.href='${origin}/?url='+encodeURIComponent(location.href)`;
}
