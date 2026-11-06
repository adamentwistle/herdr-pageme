// The panel's rules, with no Herdr imports, so `node --test` can load this file. The daemon holds the state. This only reads it
// and runs its short commands.
import { platform } from "os";

export const POLL_MS = 2000;
export const LABEL = "pageme=daemon";
export const NAME = "pageme";

export const isWindows = () => /^win/i.test(String(platform()));

// Windows has no python3.exe. That name runs the Microsoft Store's stand-in, which exits 9009 and runs nothing.
export const pythonName = (windows = isWindows()) => (windows ? "python" : "python3");

export const script = (appHome) => `${appHome}/mods/pageme/pageme.py`;

// -B keeps __pycache__ out of the mod's folder, where a new file would reload the mod.
export const command = (appHome, ...args) => ["-B", script(appHome), ...args];

// A mod's exec stops at 30 seconds, so the daemon runs as a kept terminal of its own. It has no space labels, so it stays out of
// the window, and no parent, so it outlives whatever started it.
export const startArgs = (appHome, home, windows = isWindows()) => [
  "run", "--bg", "--keep", "--no-notify", "--no-parent", "--outlive-parent",
  "--name", NAME, "--label", LABEL, "--cwd", home,
  "--", pythonName(windows), ...command(appHome, "run"),
];

export const listArgs = ["ls", "--label", LABEL, "--json"];

export function daemonAddress(stdout) {
  try {
    return JSON.parse(stdout).terminals?.[0]?.address ?? null;
  } catch {
    return null;
  }
}

export function readStatus(result) {
  if (result.code !== 0) return { status: null, problem: (result.stderr || `pageme.py stopped with code ${result.code}`).trim().slice(0, 200) };
  try {
    return { status: JSON.parse(result.stdout), problem: null };
  } catch {
    return { status: null, problem: "pageme.py printed something that isn't JSON" };
  }
}

// The big word, and the theme colour its beacon takes. `live` is whether the beacon breathes.
export function headline(status) {
  if (!status) return { text: "Unknown", tone: "dim", live: false };
  if (!status.running) return { text: "Stopped", tone: "dim", live: false };
  if (status.paused) return { text: "Paused", tone: "working", live: false };
  if (status.connected) return { text: "On call", tone: "done", live: true };
  return { text: "Not connected", tone: "blocked", live: true };
}

export const needsSetup = (status) => Boolean(status) && (!status.token || !status.paired);

export function ago(ms, now) {
  const minutes = Math.max(0, Math.floor((now - ms) / 60000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? `${hours}h` : `${Math.floor(hours / 24)}d`;
}

export const codeTime = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

export const KIND_WORDS = { asked: "Asked", answered: "Answered", refused: "Refused", finished: "Finished", paired: "Paired" };
export const kindWord = (kind) => KIND_WORDS[kind] ?? kind;

export const demoName = (demo) => (typeof demo === "string" ? demo : "on-call");

export function replyTime(ms) {
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  return seconds % 60 ? `${minutes}m ${seconds % 60}s` : `${minutes}m`;
}

// `recent` is newest first. An answer folds into the question just below it, so a page and its reply are one line.
export function timeline(recent) {
  const out = [];
  for (let i = 0; i < recent.length; i += 1) {
    const item = recent[i], next = recent[i + 1];
    if (item.kind === "answered" && next?.kind === "asked" && next.where === item.where) {
      out.push({ ...next, kind: "answered", ms: item.ms, answer: item.text });
      i += 1;
    } else {
      out.push(item);
    }
  }
  return out;
}

// The bold last line a closed message ends with. An open page has none, and shows its buttons instead.
export function pageEnding(page) {
  if (page.state === "open") return null;
  if (page.state === "used") return page.answer ? `Answered: ${page.answer}` : "Answered";
  return page.state === "expired" ? "Expired" : "Moved on";
}

// A question cut to fit the cropped phone, so its buttons stay in view.
export const clip = (text, length) => (text.length > length ? `${text.slice(0, length - 1).trimEnd()}…` : text);

export const clock = (ms) => {
  const at = new Date(ms);
  return `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
};

// on_size_change reports window pixels, and everything drawn is in the app's own units, scaled by the zoom. Until the first
// report this is the overlay's size.
export function appSize(size, zoom = 1) {
  const z = zoom > 0 ? zoom : 1;
  return size ? { width: size.width / z, height: size.height / z } : { width: 520, height: 640 };
}

// The app rounds each element to whole pixels and a path doesn't, so a length that both draw has to land on a pixel.
export const snap = (units, zoom = 1) => Math.round(units * zoom) / zoom;

export const PHONE = { ratio: 0.49, most: 680, least: 160, margin: 24 };

// The whole phone in a tab, for a pane this tall in app units: as tall as the pane allows up to `most`, at a phone's proportions,
// and centred. A short pane gets a smaller phone, never a cropped one.
export function fitPhone(height, zoom = 1) {
  const z = zoom > 0 ? zoom : 1;
  const h = snap(Math.max(PHONE.least, Math.min(PHONE.most, height - PHONE.margin * 2)), z);
  return { w: snap(h * PHONE.ratio, z), h, top: snap((height - h) / 2, z) };
}

// First run, in order. `now` is the one to do next.
export function setupSteps(status) {
  const done = [Boolean(status.token), Boolean(status.running), Boolean(status.paired)];
  const now = done.indexOf(false);
  return ["token", "daemon", "telegram"].map((name, i) => ({ name, done: done[i], now: i === now }));
}
