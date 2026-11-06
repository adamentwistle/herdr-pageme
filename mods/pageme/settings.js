// The Settings page: everything that isn't the hero. Grouped rows in the Apple style, with a switch for each on or off.
import { div } from "gpui-kit";
import { h_flex, v_flex } from "gpui-base";
import { button, iconButton, tint } from "./paint.js";

const KNOB = { duration: 140, easing: "ease-out" };

function toggle(id, on, press, t, off) {
  return div().id(id).relative().w(36).h(21).flex_none().rounded_full().bg(on ? t.done : t.raised).border(1).border_color(on ? t.done : t.input)
    .when(off, (e) => e.opacity(0.45))
    .when(!off, (e) => e.cursor_pointer().on_click(press))
    .child(div().absolute().top(1.5).left(on ? 16 : 1.5).size(16).rounded_full().bg(on ? t.background : t.muted).transition("left", KNOB));
}

const row = (label, value, t, control) => h_flex().min_h(44).px(14).gap(10).items_center()
  .child(div().flex_none().text_size(13).child(label))
  .child(div().flex_1().min_w(0).truncate().text_right().text_size(13).text_color(t.muted).child(value))
  .child(control);

function group(id, t, rows) {
  const list = v_flex().id(id).flex_none().rounded(12).bg(t.surface).border(1).border_color(t.border);
  rows.forEach((item, i) => {
    if (i) list.child(div().h(1).ml(14).bg(t.border));
    list.child(item);
  });
  return list;
}

function confirm(view, t) {
  return v_flex().id("confirm").flex_none().gap(10).p(14).rounded_b(12).bg(tint(t.blocked, "12"))
    .child(div().text_size(13).font_medium().child("Approve commands from your phone?"))
    .child(h_flex().gap(8)
      .child(button("approvals-yes", "Turn on", (_e, cx) => view.approvalsOn(cx), t, { primary: true }))
      .child(button("approvals-no", "Cancel", (_e, cx) => view.cancelConfirm(cx), t)));
}

export function settingsPage(view, status, t) {
  const paired = Boolean(status.paired), busy = view.busy;
  const connection = [
    row("Bot token", status.token ? status.token_where : "Not set", t,
      button("token", status.token ? "Replace" : "Set token", (_e, cx) => view.setToken(cx), t, { primary: !status.token })),
    row("Daemon", status.running ? (status.mode === "watch" ? "Running, watch mode" : "Running") : "Stopped", t,
      status.running
        ? button("stop", "Stop", (_e, cx) => view.stop(cx), t, { off: busy })
        : button("start", "Start", (_e, cx) => view.start(cx), t, { primary: status.token, off: busy || !status.token })),
    row("Telegram", paired ? status.paired.name : "Not paired", t,
      paired
        ? button("unpair", "Unpair", (_e, cx) => view.short(cx, "unpair"), t, { off: busy })
        : button("pair", "Pair", (_e, cx) => view.short(cx, "pair"), t, { primary: status.running, off: busy || !status.running })),
  ];
  const paging = [
    row("Messages", status.paused ? "Paused" : "", t,
      toggle("pause", !status.paused, (_e, cx) => view.short(cx, status.paused ? "resume" : "pause"), t, busy)),
    row("Other machines", "", t,
      toggle("remote", status.remote, (_e, cx) => view.short(cx, "remote", status.remote ? "off" : "on"), t, busy)),
    row("Finished", "", t,
      toggle("finished", status.finished, (_e, cx) => view.short(cx, "finished", status.finished ? "off" : "on"), t, busy)),
    row("Approving", "", t,
      toggle("approvals", status.approvals || view.confirming, (_e, cx) => view.approvalsPress(cx), t, busy)),
  ];
  if (view.confirming) paging.push(confirm(view, t));
  const trouble = view.note ?? status.error ?? view.problem;
  return v_flex().id("settings").w_full().max_w(600).h_full().min_h(0).mx_auto().gap(14).p(20)
    .child(h_flex().flex_none().gap(6).items_center().ml(-8)
      .child(iconButton("back", "chevron-left", (_e, cx) => view.closeSettings(cx), t))
      .child(div().text_size(18).font_semibold().child("Settings")))
    .child(v_flex().id("settings-list").flex_1().min_h(0).gap(14).overflow_y_scrollbar()
      .child(group("connection", t, connection))
      .when(paired, (e) => e.child(group("paging", t, paging)))
      .when(Boolean(trouble), (e) => e.child(div().id("note").flex_none().text_size(12).text_color(t.blocked).child(trouble))));
}
