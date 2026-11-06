// The phone: the latest page as Telegram shows it, drawn natively. It shows only, and nothing on it can be pressed: an answer
// is given on the real phone, where the daemon checks it.
import { div } from "gpui-kit";
import { h_flex, v_flex } from "gpui-base";
import { settings } from "herdr";
import { clip, clock, pageEnding, snap } from "./logic.js";
import { circle, gradient, icon, kept, mix, painted, pen, roundRect, tint, zoom } from "./paint.js";

function shapesFor(view, w, h, r, bezel) {
  const inner = { w: w - bezel * 2, h: h - bezel * 2 };
  return kept(view, "phone", `${w}|${h}`, () => {
    const box = { w, h }, dots = pen(1.2, box);
    for (let y = 92, row = 0; y < inner.h - 24; y += 34, row += 1) {
      for (let x = 18 + (row % 2) * 17; x < inner.w - 12; x += 34) {
        if ((x * 7 + y * 3) % 5 < 2) circle(dots, x, y, 3.5);
        else if ((x + y) % 3 === 0) dots.move_to(x - 4, y + 3).line_to(x, y - 4).line_to(x + 4, y + 3);
        else dots.move_to(x - 3, y).line_to(x + 3, y).move_to(x, y - 3).line_to(x, y + 3);
      }
    }
    return {
      body: roundRect(pen(0, box), 0, 0, w, h, r).build(),
      edge: roundRect(pen(1.5, box), 0.75, 0.75, w - 1.5, h - 1.5, r).build(),
      screen: roundRect(pen(0, box), bezel, bezel, inner.w, inner.h, r - bezel).build(),
      dots: dots.build(),
    };
  });
}

function statusBar(now, t) {
  return h_flex().absolute().left(0).right(0).top(0).h(32).px(20).items_center().justify_between()
    .child(div().text_size(11).font_semibold().child(clock(now)))
    .child(h_flex().gap(4).items_center()
      .child(h_flex().gap(1).items_end().h(9).children([4, 6, 8, 9].map((height) => div().w(2).h(height).rounded(1).bg(t.foreground))))
      .child(h_flex().w(19).h(9).p(1).rounded(3).border(1).border_color(tint(t.foreground, "66")).child(div().w(12).h_full().rounded(1).bg(t.foreground))));
}

function chatHeader(t) {
  return h_flex().absolute().left(0).right(0).top(32).h(42).px(10).gap(8).items_center().bg(t.surface).border_b(1).border_color(t.border)
    .child(icon("chevron-left", 16, t.accent))
    .child(div().flex_1().text_center().text_size(13).font_semibold().child("PageMe"))
    .child(h_flex().size(26).flex_none().items_center().justify_center().rounded_full().bg(t.accent).child(icon("bell", 14, t.accent_foreground)));
}

function bubble(page, t, width, whole) {
  const ending = pageEnding(page), fill = settings().dark ? mix(t.accent, t.raised, 0.1) : t.background;
  return v_flex().id("page").w(width).flex_none().gap(4).p(8).rounded(13).rounded_bl(4).bg(fill).shadow_sm()
    .child(div().truncate().text_size(12).font_semibold().child(page.where))
    .child(div().text_size(12).line_height(1.25).child(page.lead))
    .child(h_flex().flex_none().rounded(6).overflow_hidden().bg(tint(t.accent, "1c"))
      .child(div().w(3).h_full().flex_none().bg(t.accent))
      .child(div().id("page-text").flex_1().min_w(0).px(7).py(5).text_size(12).line_height(1.3).child(whole ? page.text : clip(page.text, 70))))
    .when(Boolean(ending), (e) => e.child(div().id("page-ending").text_size(12).font_semibold().child(ending)))
    .child(div().text_right().text_size(9).text_color(t.dim).child(clock(page.ms)));
}

function inlineButtons(page, t) {
  return v_flex().id("page-buttons").flex_none().gap(3).children(page.options.map((label, i) =>
    h_flex().id(`page-option-${i}`).h(28).flex_none().items_center().justify_center().rounded(8).px(8)
      .bg(tint(t.accent, "38")).child(div().truncate().text_size(12).font_medium().child(label))));
}

function inputBar(left, top, width, t) {
  return h_flex().absolute().left(left).top(top).w(width).h(34).px(12).items_center().rounded_full().bg(t.surface).border(1).border_color(t.border)
    .child(div().text_size(12).text_color(t.dim).child("Message"));
}

function emptyChat(t) {
  return v_flex().id("page-empty").flex_1().items_center().justify_center().gap(12)
    .child(h_flex().size(52).items_center().justify_center().rounded_full().bg(tint(t.foreground, "10")).child(icon("bell", 24, t.muted)))
    .child(div().px(10).py(3).rounded_full().bg(tint(t.foreground, "10")).text_size(12).text_color(t.muted).child("Nothing yet"));
}

function sentCode(status, t) {
  return v_flex().flex_1().gap(6).items_end()
    .child(v_flex().id("page-code").flex_none().px(11).py(7).gap(1).rounded(13).rounded_br(4).bg(t.accent)
      .child(div().font_family("JetBrains Mono").text_size(13).font_semibold().text_color(t.accent_foreground).child(status.code.value)))
    .child(h_flex().px(10).py(7).gap(3).self_start().rounded(13).rounded_bl(4).bg(t.raised)
      .children([1400, 1700, 2000].map((period) => div().size(5).rounded_full().bg(t.muted).loop("opacity", { from: 0.25, to: 1, period }))));
}

// `h` runs past what's shown when the phone stands in a stage that crops it.
export function phone(view, status, now, { w, h, whole = false, shown = h }, t) {
  const r = 34, dark = settings().dark, bezel = snap(7, zoom());
  const shapes = shapesFor(view, w, h, r, bezel);
  const inner = w - bezel * 2, page = status?.latest;
  const body = dark ? mix(t.foreground, t.canvas, 0.14) : mix(t.foreground, t.background, 0.86);
  const content = status?.code
    ? sentCode(status, t)
    : page
      ? v_flex().flex_none().gap(3).child(bubble(page, t, inner - 20, whole)).when(page.state === "open" && page.options.length > 0, (e) => e.child(inlineButtons(page, t)))
      : emptyChat(t);
  return div().id("phone").relative().w(w).h(h).flex_none()
    .child(div().absolute().left(0).top(0).w(w).h(h).rounded(r).shadow_2xl())
    .child(painted(shapes.body, body, w, h))
    .child(painted(shapes.screen, gradient(165, mix(t.accent, t.background, dark ? 0.16 : 0.2), mix(t.accent, t.background, dark ? 0.05 : 0.08)), w, h))
    .child(painted(shapes.dots, tint(t.foreground, dark ? "0a" : "10"), w, h).left(bezel).top(bezel))
    .child(painted(shapes.edge, gradient(135, tint(t.foreground, dark ? "66" : "33"), tint(t.foreground, "08")), w, h))
    .child(div().absolute().left(bezel).top(bezel).w(inner).h(74).rounded_t(r - bezel).bg(t.surface)
      .child(statusBar(now, t))
      .child(chatHeader(t))
      .child(div().absolute().top(8).left((inner - 62) / 2).w(62).h(17).rounded_full().bg(dark ? t.chrome : t.foreground)))
    .child(v_flex().absolute().left(bezel + 10).top(bezel + 82).w(inner - 20).h(Math.max(0, shown - bezel * 2 - (whole ? 142 : 94))).overflow_hidden().when(whole, (e) => e.justify_end()).child(content))
    .when(whole, (e) => e.child(inputBar(bezel + 10, h - bezel - 48, inner - 20, t)));
}
