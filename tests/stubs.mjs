// Stand-ins for Herdr's modules, so the mod's own files can run under `node --test`. An element records every call, so a test
// can read its text and press what's pressable. This proves the mod's logic, not that the real app accepts its calls:
// `herdr-app check` does that.
import { registerHooks } from "node:module";

export class El {
  constructor(tag) { this.tag = tag; this.kids = []; this.calls = []; this.press = null; this.elementId = null; }
  child(value) { if (value !== undefined && value !== null) this.kids.push(value); return this; }
  children(list) { for (const value of list) this.child(value); return this; }
  when(on, change) { return on ? change(this) : this; }
  on_click(press) { this.press = press; return this; }
  id(value) { this.elementId = value; return this; }
  hover(style) { style(element("hover")); return this; }
  text() { return this.kids.map((k) => (k instanceof El ? k.text() : String(k))).join(" "); }
  find(id) {
    if (this.elementId === id) return this;
    for (const k of this.kids) {
      const found = k instanceof El ? k.find(id) : null;
      if (found) return found;
    }
    return null;
  }
}

export const element = (tag) => new Proxy(new El(tag), {
  get(target, name, self) {
    if (name in target || typeof name === "symbol") {
      const value = target[name];
      return typeof value === "function" ? value.bind(self) : value;
    }
    return (...args) => { target.calls.push([name, args]); return self; };
  },
});

// What the fake `herdr` module reads. A test sets these.
export const world = {
  exec: async () => ({ code: 0, stdout: "{}", stderr: "" }),
  hc: async () => ({ code: 0, stdout: "{}", stderr: "" }),
  run: () => null,
  props: {},
  dark: true,
  zoom: 1,
  drawn: [],
};

export const theme = Object.fromEntries(["background", "canvas", "chrome", "surface", "popover", "raised", "hover", "border", "input", "foreground", "muted", "dim", "accent", "accent_foreground",
  "solid", "solid_foreground", "blocked", "done", "idle", "working"]
  .map((name, i) => [name, `#${String(i + 10).repeat(3)}`]));

// Whatever a path is asked, it answers with itself, and the real checks on geometry are `herdr-app check` and a frame.
const pen = () => new Proxy({}, { get: (_t, name, self) => (name === "build" ? () => ({}) : (...args) => { world.drawn.push([name, ...args]); return self; }) });
export const pathBuilder = { fill: pen, stroke: (width) => { world.drawn.push(["stroke", width]); return pen(); } };
export const backgrounds = { linear_gradient: () => ({}) };
globalThis.window = { paint_path: () => element("path") };

const stubs = {
  "gpui-kit": `import { backgrounds, element, pathBuilder } from ${JSON.stringify(import.meta.url)};
export class View {}
export const div = () => element("div");
export const svg = () => element("svg");
export const PathBuilder = pathBuilder;
export const Background = backgrounds;`,
  "gpui-base": `import { element } from ${JSON.stringify(import.meta.url)};
export const v_flex = () => element("v_flex");
export const h_flex = () => element("h_flex");`,
  herdr: `import { world, theme as colours } from ${JSON.stringify(import.meta.url)};
export const appHome = () => "/h/.config/herdr-app";
export const home = () => "/h";
export const exec = (...args) => world.exec(...args);
export const hc = (...args) => world.hc(...args);
export const run = (...args) => world.run(...args);
export const props = () => world.props;
export const settings = () => ({ dark: world.dark, zoom: world.zoom });
export const theme = () => colours;`,
};

registerHooks({
  resolve(specifier, context, next) {
    if (specifier in stubs) return { url: `stub:${specifier}`, shortCircuit: true };
    return next(specifier, context);
  },
  load(url, context, next) {
    if (url.startsWith("stub:")) return { format: "module", source: stubs[url.slice(5)], shortCircuit: true };
    return next(url, context);
  },
});

// A cx whose tasks can be waited for, and whose timers are held so a test runs them by hand.
export function fakeCx() {
  const tasks = [];
  const cx = {
    notified: 0, repeating: [],
    notify() { this.notified += 1; },
    spawn(body) { tasks.push(body(cx)); },
    timer: { every(ms, handler) { const task = { ms, handler }; cx.repeating.push(task); return task; } },
    settled: async () => { while (tasks.length) await tasks.shift(); },
  };
  return cx;
}
