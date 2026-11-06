// Draws the panel. Colours are theme names only. Two shapes: the 520 by 640 overlay, with the phone beside the hero and cropped
// by the stage, and a wide tab, with the whole phone in a column of its own.
import { div } from "gpui-kit";
import { h_flex, v_flex } from "gpui-base";
import { theme } from "herdr";
import { ago, appSize, codeTime, fitPhone, headline, kindWord, needsSetup, replyTime, setupSteps, snap, timeline } from "./logic.js";
import { button, circle, gradient, icon, iconButton, kept, mix, painted, pen, roundRect, tint, zoom } from "./paint.js";
import { phone } from "./phone.js";
import { settingsPage } from "./settings.js";

const WIDE = 640;
const STAGE = 376;
const ROW = 34;
const PHONE_W = 232;
const PHONE_TOP = 40;
const RINGS = [["50", 46], ["3c", 88], ["2c", 134], ["20", 186], ["16", 244], ["0e", 310], ["0a", 384], ["07", 470]];
const GLOW = Array.from({ length: 18 }, (_, i) => 30 + i * 15);
const HALO = Array.from({ length: 16 }, (_, i) => 2 + i * 3);

const tones = (t) => ({ done: t.done, blocked: t.blocked, working: t.working, accent: t.accent, dim: t.dim });

function wash(view, width, height, colour) {
  const shape = kept(view, "wash", `${width}|${height}`, () => roundRect(pen(0, { w: width, h: height }), 0, 0, width, height, 0).build());
  return painted(shape, gradient(180, tint(colour, "14"), tint(colour, "00")), width, height);
}

// The rings and glow are the beacon's own children, so they stay centred on it wherever the layout puts it and at any zoom.
function beacon(view, colour, live) {
  const core = 14, halo = 34, reach = RINGS.at(-1)[1] + 2;
  const rings = kept(view, "rings", "", () => RINGS.map(([, r]) => circle(pen(1, { w: reach * 2, h: reach * 2 }), reach, reach, r).build()));
  const glow = div().absolute().left(18).top(18).size(0)
    .children(GLOW.map((size) => div().absolute().left(-size / 2).top(-size / 2).size(size).rounded_full().bg(tint(colour, "05"))))
    .when(live, (e) => e.loop("opacity", { from: 0.55, to: 1, period: 3600 }));
  return div().id("beacon").relative().w(36).h(36).flex_none()
    .children(RINGS.map(([alpha], i) => painted(rings[i], tint(colour, alpha), reach * 2, reach * 2).left(18 - reach).top(18 - reach)))
    .child(glow)
    .when(live, (e) => e.child(div().absolute().left(18 - halo / 2).top(18 - halo / 2).size(halo).rounded_full().bg(tint(colour, "44")).loop("opacity", { from: 0.2, to: 1, period: 1800 })))
    .child(div().absolute().left(18 - core / 2).top(18 - core / 2).size(core).rounded_full().bg(colour));
}

// The last 24 hours, oldest at the left. An hour with no pages keeps a stub, so the strip reads as a day.
function hours(view, status, width, colour, t) {
  const list = status.today.hours;
  const height = 40, gap = 3, step = (width + gap) / list.length, most = Math.max(...list);
  const shapes = kept(view, "hours", `${list.join("")}|${width}`, () => {
    const box = { w: width, h: height }, bars = pen(0, box), stubs = pen(0, box);
    list.forEach((count, i) => {
      const x = i * step, w = step - gap, top = count ? height - Math.max(6, (height - 2) * (count / most)) : height - 2;
      roundRect(count ? bars : stubs, x, top, w, height - top, count ? 1.5 : 1);
    });
    return { bars: bars.build(), stubs: stubs.build() };
  });
  return div().id("hours").relative().w(width).h(height).flex_none()
    .child(painted(shapes.stubs, t.border, width, height))
    .child(painted(shapes.bars, gradient(180, colour, tint(colour, "66")), width, height));
}

// A soft light behind the phone, in the state's colour, so it lifts off the panel.
function halo(view, x, y, w, h, colour) {
  return HALO.map((grow) => div().absolute().left(x - grow).top(y - grow).w(w + grow * 2).h(h + grow * 2).rounded(34 + grow).bg(tint(colour, "02")));
}

function stat(id, value, word, t) {
  return v_flex().id(id).flex_none().gap(1)
    .child(div().text_size(22).line_height(1.1).font_semibold().child(value))
    .child(div().text_size(11).text_color(t.muted).child(word));
}

function stats(status, t) {
  const today = status.today ?? { pages: 0, answered: 0, reply_ms: null };
  return h_flex().id("stats").flex_none().gap(20)
    .child(stat("stat-pages", String(today.pages), "Pages", t))
    .child(stat("stat-answered", String(today.answered), "Answered", t))
    .when(today.reply_ms !== null, (e) => e.child(stat("stat-reply", replyTime(today.reply_ms), "Reply", t)));
}

function who(status, t) {
  const name = status.paired?.name ?? "";
  return h_flex().id("who").flex_none().gap(7).items_center()
    .child(h_flex().size(20).flex_none().items_center().justify_center().rounded_full().bg(t.raised).text_size(10).font_semibold().child(name.slice(0, 1).toUpperCase()))
    .child(div().text_size(14).text_color(t.muted).child(name));
}

function action(view, status, t) {
  if (!status.running) return button("start", "Start", (_e, cx) => view.start(cx), t, { primary: true, off: view.busy || !status.token });
  if (status.paused) return button("pause", "Resume", (_e, cx) => view.short(cx, "resume"), t, { primary: true, off: view.busy });
  return null;
}

function hero(view, status, t) {
  const line = headline(status), trouble = view.note ?? status.error ?? view.problem, press = action(view, status, t);
  return v_flex().id("hero").flex_none().gap(8)
    .child(div().id("headline").text_size(line.text.length > 8 ? 32 : 46).line_height(1.05).font_semibold().child(line.text))
    .child(who(status, t))
    .when(Boolean(trouble), (e) => e.child(div().id("note").text_size(12).line_height(1.35).text_color(t.blocked).child(trouble)))
    .when(Boolean(press), (e) => e.child(h_flex().pt(4).child(press)));
}

const KINDS = (t) => ({
  asked: ["message", t.accent], answered: ["check", t.done], refused: ["x", t.blocked], finished: ["flag", t.muted], paired: ["link", t.accent],
});

function entry(item, i, count, now, t) {
  const [glyph, colour] = KINDS(t)[item.kind] ?? ["message", t.muted];
  const refused = item.kind === "refused";
  return h_flex().id(`recent-${i}`).relative().h(ROW).flex_none().items_center().gap(10).px(6).rounded(8)
    .when(refused, (e) => e.bg(tint(t.blocked, "1a")))
    .when(count > 1, (e) => e.child(div().absolute().left(15).w(1).top(i === 0 ? ROW / 2 : 0).h(i === 0 || i === count - 1 ? ROW / 2 : ROW).bg(t.border)))
    .child(h_flex().size(19).flex_none().items_center().justify_center().rounded_full().bg(mix(colour, t.canvas, refused ? 0.32 : 0.18)).child(icon(glyph, 11, colour)))
    .when(refused, (e) => e.child(div().flex_none().text_size(12).font_semibold().text_color(t.blocked).child(kindWord(item.kind))))
    .child(div().flex_1().min_w(0).truncate().text_size(refused ? 12 : 13).child(item.text))
    .when(Boolean(item.answer), (e) => e.child(div().flex_none().max_w(96).truncate().px(6).py(1).rounded(5).bg(tint(t.done, "20")).text_size(11).font_medium().text_color(t.done).child(item.answer)))
    .child(div().flex_none().max_w(128).truncate().text_size(11).text_color(t.dim).child(item.where))
    .child(div().flex_none().w(24).text_right().text_size(11).text_color(t.dim).child(ago(item.ms, now)));
}

// In the overlay the timeline fills what's left. In a tab it's only as tall as its rows, and shrinks and scrolls when they don't fit.
function activity(status, now, t, fill = true) {
  const list = timeline(status.recent ?? []);
  const box = v_flex().id("recent").min_h(0);
  return (fill ? box.flex_1() : box.flex_basis(list.length * ROW).flex_shrink(1))
    .child(v_flex().id("recent-list").flex_1().min_h(0).overflow_y_scrollbar()
      .children(list.map((item, i) => entry(item, i, list.length, now, t))));
}

function disclosure(t) {
  return div().id("disclosure").flex_none().text_size(12).text_color(t.muted).line_height(1.45)
    .child("Blocked agents' screen text goes to Telegram. Bot chats aren't end-to-end encrypted. Likely secrets are hidden first, and that can miss some.");
}

function step(number, label, item, press, t) {
  const on = item.now;
  return h_flex().id(`step-${item.name}`).h(46).flex_none().px(14).gap(12).items_center()
    .child(h_flex().size(22).flex_none().items_center().justify_center().rounded_full().text_size(11).font_semibold()
      .bg(item.done ? tint(t.done, "26") : on ? t.solid : t.raised).text_color(on ? t.solid_foreground : t.muted)
      .child(item.done ? icon("check", 12, t.done) : String(number)))
    .child(div().flex_1().text_size(13).font_medium().text_color(item.done || on ? t.foreground : t.muted).child(label))
    .child(press);
}

function steps(view, status, t) {
  const [token, daemon, telegram] = setupSteps(status);
  const list = v_flex().id("steps").flex_none().rounded(12).bg(t.surface).border(1).border_color(t.border);
  list.child(step(1, "Bot token", token, button("token", status.token ? "Replace" : "Set token", (_e, cx) => view.setToken(cx), t, { primary: !status.token }), t));
  list.child(div().h(1).ml(48).bg(t.border));
  list.child(step(2, "Daemon", daemon, status.running
    ? button("stop", "Stop", (_e, cx) => view.stop(cx), t, { off: view.busy })
    : button("start", "Start", (_e, cx) => view.start(cx), t, { primary: status.token, off: view.busy || !status.token }), t));
  list.child(div().h(1).ml(48).bg(t.border));
  list.child(step(3, "Telegram", telegram, status.paired
    ? button("unpair", "Unpair", (_e, cx) => view.short(cx, "unpair"), t, { off: view.busy })
    : button("pair", "Pair", (_e, cx) => view.short(cx, "pair"), t, { primary: status.running, off: view.busy || !status.running }), t));
  return list;
}

function code(status, t, tile) {
  const { value, seconds } = status.code;
  return v_flex().id("code").flex_none().gap(10)
    .child(h_flex().id("code-value").flex_none().gap(6).justify_center().children([...value].map((letter) =>
      h_flex().w(tile).h(Math.round(tile * 1.3)).flex_none().items_center().justify_center().rounded(10).bg(t.surface).border(1).border_color(t.input)
        .font_family("JetBrains Mono").text_size(Math.round(tile * 0.58)).font_semibold().text_color(t.accent).child(letter))))
    .child(h_flex().flex_none().gap(10).items_center()
      .child(div().relative().flex_1().h(3).rounded_full().bg(t.raised)
        .child(div().absolute().left(0).top(0).h(3).rounded_full().bg(t.accent).w(`${Math.min(100, seconds / 3)}%`).transition("width", 400)))
      .child(div().flex_none().text_size(12).text_color(t.muted).child(codeTime(seconds))));
}

function setupBody(view, status, t, tile) {
  const trouble = view.note ?? status.error ?? view.problem;
  return v_flex().flex_none().gap(14)
    .child(status.code ? code(status, t, tile) : steps(view, status, t))
    .when(Boolean(trouble), (e) => e.child(div().id("note").text_size(12).text_color(t.blocked).child(trouble)))
    .child(disclosure(t));
}

function setupHero(status, t) {
  return v_flex().id("hero").flex_none().gap(8)
    .child(div().id("headline").text_size(46).line_height(1.05).font_semibold().child(status.code ? "Pair" : "Set up"))
    .when(Boolean(status.code), (e) => e.child(div().text_size(14).text_color(t.muted).child("Send this to your bot")));
}

const busyDay = (status) => Boolean(status.today?.hours?.some(Boolean));

const gear = (view, t) => iconButton("gear", "settings", (_e, cx) => view.openSettings(cx), t);

const demoChip = (t) => div().px(6).py(1).rounded(4).bg(t.raised).text_size(10).text_color(t.dim).child("Demo");

function topRight(view, status, t) {
  return h_flex().absolute().top(8).right(10).gap(6).items_center()
    .when(Boolean(status.demo), (e) => e.child(demoChip(t)))
    .child(gear(view, t));
}

function fadeOut(view, width, t) {
  const shape = kept(view, "fade", String(width), () => roundRect(pen(0, { w: width, h: 34 }), 0, 0, width, 34, 0).build());
  return div().absolute().left(0).bottom(0).w(width).h(34).child(painted(shape, gradient(180, tint(t.canvas, "00"), tint(t.canvas, "ff")), width, 34));
}

function compact(view, status, now, { width, height }, t, colour, live) {
  const setup = needsSetup(status), z = zoom(), phoneW = snap(PHONE_W, z);
  const column = width - phoneW - 62;
  const left = v_flex().absolute().left(22).top(14).w(column).gap(16)
    .child(beacon(view, colour, live))
    .child(setup ? setupHero(status, t) : hero(view, status, t))
    .when(!setup, (e) => e.child(stats(status, t)).when(busyDay(status), (s) => s.child(hours(view, status, column, colour, t))));
  const quiet = !setup && !(status.recent ?? []).length;
  const stageHeight = snap(quiet ? height : setup ? Math.max(280, height - 244) : Math.min(STAGE, Math.max(240, height - 170)), z);
  const phoneX = snap(width - phoneW - 20, z);
  const whole = quiet;
  const phoneH = snap(whole ? height - PHONE_TOP - 22 : 470, z);
  return v_flex().size_full().min_h(0)
    .child(div().id("stage").relative().w_full().h(stageHeight).flex_none().overflow_hidden()
      .child(wash(view, width, stageHeight, colour))
      .child(left)
      .children(halo(view, phoneX, PHONE_TOP, phoneW, phoneH, colour))
      .child(div().absolute().left(phoneX).top(PHONE_TOP).child(phone(view, status, now, { w: phoneW, h: phoneH, whole, shown: whole ? phoneH : stageHeight - PHONE_TOP + 40 }, t)))
      .when(!whole, (e) => e.child(fadeOut(view, width, t)))
      .child(topRight(view, status, t)))
    .when(setup, (e) => e.child(v_flex().flex_1().min_h(0).px(22).pt(6).child(setupBody(view, status, t, Math.floor((width - 44 - 42) / 8)))))
    .when(!setup && !quiet, (e) => e.child(v_flex().flex_1().min_h(0).px(14).pb(10).child(activity(status, now, t))));
}

function wide(view, status, now, { width, height }, t, colour, live) {
  const setup = needsSetup(status), fit = fitPhone(height, zoom());
  const column = width - fit.w - 156 - 44;
  return h_flex().size_full().min_h(0).items_stretch()
    .child(div().absolute().left(0).top(0).w(width).h(height).child(wash(view, width, height, colour)))
    .child(v_flex().id("column").flex_1().min_w(0).min_h(0).px(22).py(fit.top).gap(20).justify_center()
      .child(beacon(view, colour, live))
      .child(setup ? setupHero(status, t) : hero(view, status, t))
      .when(!setup, (e) => e.child(stats(status, t))
        .when(busyDay(status), (s) => s.child(hours(view, status, Math.min(420, column), colour, t)))
        .child(activity(status, now, t, false)))
      .when(setup, (e) => e.child(setupBody(view, status, t, Math.min(46, Math.floor((column - 42) / 8))))))
    .child(div().relative().w(fit.w + 156).h_full().flex_none()
      .children(halo(view, 60, fit.top, fit.w, fit.h, colour))
      .child(div().absolute().left(60).top(fit.top).child(phone(view, status, now, { w: fit.w, h: fit.h, whole: true }, t))))
    .child(div().absolute().top(0).right(0).child(topRight(view, status, t)));
}

export function panel(view, now) {
  const t = theme();
  const { status, problem } = view;
  const { width, height } = appSize(view.size, zoom());
  const root = div().id("pageme").relative().size_full().min_h(0).min_w(0).overflow_hidden().bg(t.canvas).text_color(t.foreground)
    .on_size_change((size, cx) => view.resized(size, cx));
  if (!status) {
    return root.child(v_flex().p(22).child(div().id("problem").text_size(13).text_color(problem ? t.blocked : t.muted).child(problem ?? "Reading")));
  }
  if (view.settings) return root.child(settingsPage(view, status, t));
  const setup = needsSetup(status);
  const line = headline(status);
  const colour = setup ? t.accent : tones(t)[line.tone];
  const live = setup ? Boolean(status.code) : line.live;
  return root
    .child((width >= WIDE ? wide : compact)(view, status, now, { width, height }, t, colour, live));
}
