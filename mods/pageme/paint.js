// Drawing helpers. Paths are kept on the view and made again only when their key changes, because a render has about 55 ms.
import { Background, PathBuilder, div, svg } from "gpui-kit";
import { h_flex } from "gpui-base";
import { settings } from "herdr";

export const tint = (colour, alpha) => `${colour.slice(0, 7)}${alpha}`;

// `colour` laid over `under` at `share`, as one solid colour, for anything a line must not show through.
export function mix(colour, under, share) {
  const rgb = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  if (!/^#[0-9a-f]{6}/i.test(colour ?? "") || !/^#[0-9a-f]{6}/i.test(under ?? "")) return colour;
  const [a, b] = [rgb(colour), rgb(under)];
  return `#${a.map((v, i) => Math.round(v * share + b[i] * (1 - share)).toString(16).padStart(2, "0")).join("")}`;
}

export const gradient = (angle, from, to) => Background.linear_gradient(angle, from, to);

export const painted = (path, paint, width, height) => window.paint_path(path, paint).absolute().top(0).left(0).w(width).h(height);

export const zoom = () => settings().zoom || 1;

export function kept(view, name, key, make) {
  const hit = view.paths[name];
  if (hit?.key === key) return hit.value;
  const value = make();
  view.paths[name] = { key, value };
  return value;
}

// Takes numbers in the app's units for a path painted in a box of `w` by `h`, and writes them as shares of that box. A share
// means the same at any zoom, so a path always lands on the elements drawn beside it. A stroke width of 0 makes a fill.
export function pen(stroke, { w, h }) {
  const path = stroke ? PathBuilder.stroke(stroke) : PathBuilder.fill();
  const share = (value, size) => `${Number(((value / size) * 100).toFixed(4))}%`;
  const across = (x) => share(x, w), down = (y) => share(y, h);
  return {
    move_to(x, y) { path.move_to(across(x), down(y)); return this; },
    line_to(x, y) { path.line_to(across(x), down(y)); return this; },
    arc_to(rx, ry, turn, large, sweep, x, y) { path.arc_to(across(rx), down(ry), turn, large, sweep, across(x), down(y)); return this; },
    close() { path.close(); return this; },
    build: () => path.build(),
  };
}

export function roundRect(path, x, y, w, h, r) {
  return path.move_to(x + r, y).line_to(x + w - r, y).arc_to(r, r, 0, false, true, x + w, y + r)
    .line_to(x + w, y + h - r).arc_to(r, r, 0, false, true, x + w - r, y + h)
    .line_to(x + r, y + h).arc_to(r, r, 0, false, true, x, y + h - r)
    .line_to(x, y + r).arc_to(r, r, 0, false, true, x + r, y).close();
}

export const circle = (path, x, y, r) => path.move_to(x - r, y).arc_to(r, r, 0, true, true, x + r, y).arc_to(r, r, 0, true, true, x - r, y).close();

export const icon = (name, size, colour) => svg(`mods/pageme/icons/${name}.svg`).size(size).flex_none().text_color(colour);

export function button(id, text, press, t, { primary = false, off = false } = {}) {
  return div().id(id).h(30).px(12).flex().items_center().rounded(8).text_size(12).font_medium().flex_none()
    .bg(primary ? t.solid : t.raised).text_color(primary ? t.solid_foreground : t.foreground)
    .child(text)
    .when(off, (e) => e.opacity(0.45))
    .when(!off, (e) => e.cursor_pointer().hover((s) => s.opacity(0.88)).on_click(press));
}

export function iconButton(id, name, press, t) {
  return h_flex().id(id).size(30).flex_none().items_center().justify_center().rounded(8).cursor_pointer()
    .hover((s) => s.bg(t.hover)).on_click(press).child(icon(name, 16, t.muted));
}
