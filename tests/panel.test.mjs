// Runs main.js and view.js against the stand-ins in stubs.mjs: every state the panel can be in, and every control.
import assert from "node:assert/strict";
import test from "node:test";
import { fakeCx, world } from "./stubs.mjs";

const { default: PageMe } = await import("../mods/pageme/main.js");
const logic = await import("../mods/pageme/logic.js");

const base = {
  demo: false, token: true, token_where: "Windows Credential Manager", running: true, connected: true, error: null,
  paired: { name: "Sam", ms: 1 }, code: null, paused: false, mode: "act", approvals: false, finished: false, recent: [],
  latest: null, today: { pages: 0, answered: 0, reply_ms: null, hours: Array(24).fill(0) },
};
const settings = { page: "settings" };
const page = { ms: 1, where: "mac/t4 · sample-app", lead: "Claude Code has a question", text: "Which pet?", options: ["Cat", "Dog"], state: "open", answer: null };
const reply = (value) => ({ code: 0, stdout: JSON.stringify(value), stderr: "" });

// A panel showing `status`. Each exec is kept, and a status call gets `status`.
async function open(status, initial = {}) {
  const asked = [];
  world.exec = async (cmd, args) => { asked.push({ cmd, args }); return reply(status); };
  world.hc = async () => reply({ terminals: [] });
  world.run = () => null;
  const panel = new PageMe();
  const cx = fakeCx();
  panel.init(initial, cx);
  await cx.settled();
  return { panel, cx, asked, draw: () => panel.render(), press: async (id) => { panel.render().find(id).press({}, cx); await cx.settled(); } };
}
const shortCalls = (asked) => asked.map((a) => a.args.slice(2)).filter((a) => a[0] !== "status");

test("on call shows the hero and who it pages, with no form on it", async () => {
  const { draw } = await open(base);
  assert.equal(draw().find("headline").text(), "On call");
  assert.match(draw().find("who").text(), /Sam/);
  for (const id of ["token", "unpair", "pause", "remote", "finished", "approvals", "stop"]) assert.equal(draw().find(id), null, id);
});

test("the gear opens Settings, with every control, and the back button leaves it", async () => {
  const { draw, press } = await open(base);
  await press("gear");
  for (const id of ["token", "unpair", "pause", "remote", "finished", "approvals", "stop"]) assert.ok(draw().find(id), id);
  assert.equal(draw().find("phone"), null);
  await press("back");
  assert.equal(draw().find("settings"), null);
  assert.ok(draw().find("phone"));
});

test("each state has its headline and colour", () => {
  assert.deepEqual(logic.headline({ ...base, running: false }), { text: "Stopped", tone: "dim", live: false });
  assert.deepEqual(logic.headline({ ...base, paused: true }), { text: "Paused", tone: "working", live: false });
  assert.deepEqual(logic.headline({ ...base, connected: false }), { text: "Not connected", tone: "blocked", live: true });
  assert.deepEqual(logic.headline(base), { text: "On call", tone: "done", live: true });
});

test("Paused and Stopped put the way out on the hero", async () => {
  const paused = await open({ ...base, paused: true });
  assert.match(paused.draw().find("pause").text(), /Resume/);
  await paused.press("pause");
  assert.deepEqual(shortCalls(paused.asked), [["resume"]]);
  const stopped = await open({ ...base, running: false, connected: false });
  assert.ok(stopped.draw().find("start").press);
});

test("the phone shows the latest page with its buttons, and none of them can be pressed", async () => {
  const { draw } = await open({ ...base, latest: page });
  assert.match(draw().find("page").text(), /mac\/t4 · sample-app/);
  assert.match(draw().find("page").text(), /Claude Code has a question/);
  assert.equal(draw().find("page-text").text(), "Which pet?");
  assert.match(draw().find("page-buttons").text(), /Cat/);
  assert.match(draw().find("page-buttons").text(), /Dog/);
  assert.equal(draw().find("page-option-0").press, null);
  assert.equal(draw().find("page-ending"), null);
});

test("a closed page loses its buttons and ends the way the message does", async () => {
  const cases = [[{ state: "used", answer: "Dog" }, "Answered: Dog"], [{ state: "gone" }, "Moved on"], [{ state: "expired" }, "Expired"]];
  for (const [change, ending] of cases) {
    const { draw } = await open({ ...base, latest: { ...page, ...change } });
    assert.equal(draw().find("page-buttons"), null);
    assert.equal(draw().find("page-ending").text(), ending);
  }
});

test("a long question is cut in the cropped phone, so its buttons stay in view", async () => {
  const { draw } = await open({ ...base, latest: { ...page, text: "x".repeat(110) }, recent: [{ ms: 1, kind: "asked", where: "t1", text: "x" }] });
  assert.ok(draw().find("page-text").text().length <= 70);
});

test("with no page the phone is calm", async () => {
  const { draw } = await open(base);
  assert.match(draw().find("page-empty").text(), /Nothing yet/);
  assert.equal(draw().find("page"), null);
  assert.equal(draw().find("recent"), null);
});

test("the numbers come from status, and Reply waits for an answer", async () => {
  const none = await open(base);
  assert.match(none.draw().find("stat-pages").text(), /0/);
  assert.equal(none.draw().find("stat-reply"), null);
  assert.equal(none.draw().find("hours"), null);
  const hours = Array(24).fill(0); hours[23] = 2;
  const busy = await open({ ...base, today: { pages: 3, answered: 2, reply_ms: 100000, hours } });
  assert.match(busy.draw().find("stat-pages").text(), /3/);
  assert.match(busy.draw().find("stat-answered").text(), /2/);
  assert.match(busy.draw().find("stat-reply").text(), /1m 40s/);
  assert.ok(busy.draw().find("hours"));
});

test("a wide tab draws every state too", async () => {
  for (const status of [{ ...base, latest: page }, base, { ...base, paired: null }, { ...base, paired: null, code: { value: "ABCD2345", seconds: 125 } }]) {
    const { panel, cx, draw } = await open(status);
    panel.resized({ width: 1000, height: 700 }, cx);
    assert.ok(draw().find("phone"));
    assert.ok(draw().find("hero"));
  }
});

const ZOOMS = [1, 1.1, 1.2, 1.5];
const called = (element, name) => element.calls.findLast(([call]) => call === name)?.[1][0];
const close = (a, b, within) => assert.ok(Math.abs(a - b) <= within, `${a} is not within ${within} of ${b}`);

test("the phone fits the pane and sits centred at any zoom", () => {
  for (const zoom of ZOOMS) {
    for (const px of [420, 500, 640, 800, 900, 1000, 1400]) {
      const { height } = logic.appSize({ width: 1200, height: px }, zoom);
      const { w, h, top } = logic.fitPhone(height, zoom);
      assert.ok(top >= 0, `top at ${px}px, zoom ${zoom}`);
      assert.ok(top + h <= height + 1 / zoom, `bottom at ${px}px, zoom ${zoom}`);
      close(top, height - top - h, 2 / zoom);
      close(w / h, logic.PHONE.ratio, 0.01);
      close(h * zoom, Math.round(h * zoom), 1e-6);
      close(w * zoom, Math.round(w * zoom), 1e-6);
    }
  }
});

test("a short pane gets a smaller phone, and a tall one stops growing", () => {
  const small = logic.fitPhone(400), large = logic.fitPhone(1200);
  assert.equal(small.h, 352);
  assert.ok(small.w < large.w);
  assert.equal(large.h, logic.PHONE.most);
  assert.equal(large.top, 260);
});

test("a window pixel size becomes app units, and the overlay is the size to start from", () => {
  assert.deepEqual(logic.appSize({ width: 1200, height: 900 }, 1.2), { width: 1000, height: 750 });
  assert.deepEqual(logic.appSize(null, 1.2), { width: 520, height: 640 });
  assert.deepEqual(logic.appSize({ width: 300, height: 200 }, 0), { width: 300, height: 200 });
});

test("a tab draws its phone inside the pane at any zoom", async () => {
  for (const zoom of ZOOMS) {
    world.zoom = zoom;
    const { panel, cx, draw } = await open({ ...base, latest: page });
    panel.resized({ width: 1280, height: 900 }, cx);
    const element = draw().find("phone");
    close(called(element, "h") * zoom, Math.min(logic.PHONE.most * zoom, 900 - logic.PHONE.margin * 2 * zoom), 1);
    assert.ok(draw().find("column"));
    panel.resized({ width: 1280, height: 400 }, cx);
    assert.ok(called(draw().find("phone"), "h") * zoom <= 400);
  }
  world.zoom = 1;
});

test("the overlay keeps its shape whatever the zoom", async () => {
  for (const zoom of ZOOMS) {
    world.zoom = zoom;
    const { panel, cx, draw } = await open({ ...base, latest: page, recent: [{ ms: 1, kind: "asked", where: "t1", text: "x" }] });
    panel.resized({ width: 520 * zoom, height: 640 * zoom }, cx);
    assert.ok(draw().find("stage"));
    assert.equal(draw().find("column"), null);
  }
  world.zoom = 1;
});

test("a path is written as shares of its box, so no zoom can move it", async () => {
  const paint = await import("../mods/pageme/paint.js");
  for (const zoom of ZOOMS) {
    world.zoom = zoom; world.drawn = [];
    paint.pen(1.5, { w: 200, h: 100 }).move_to(50, 25).line_to(200, 100).arc_to(20, 20, 0, false, true, 100, 50);
    assert.deepEqual(world.drawn, [["stroke", 1.5], ["move_to", "25%", "25%"], ["line_to", "100%", "100%"], ["arc_to", "10%", "20%", 0, false, true, "50%", "50%"]]);
  }
  world.zoom = 1;
});

test("the light theme draws too", async () => {
  world.dark = false;
  const { draw } = await open({ ...base, latest: page });
  assert.ok(draw().find("page"));
  world.dark = true;
});

test("setup goes in order, and shows no numbers yet", async () => {
  const first = logic.setupSteps({ ...base, token: false, running: false, paired: null });
  assert.deepEqual(first.map((s) => s.now), [true, false, false]);
  const last = logic.setupSteps({ ...base, paired: null });
  assert.deepEqual(last.map((s) => s.done), [true, true, false]);
  assert.deepEqual(last.map((s) => s.now), [false, false, true]);
  const { draw } = await open({ ...base, paired: null });
  assert.ok(draw().find("steps"));
  assert.equal(draw().find("stats"), null);
});

test("paired with the token gone, setup offers Unpair and not Pair", async () => {
  const { draw } = await open({ ...base, token: false, running: false, connected: false });
  assert.ok(draw().find("unpair"));
  assert.equal(draw().find("pair"), null);
});

test("setup says what leaves the machine", async () => {
  const { draw } = await open({ ...base, paired: null });
  const text = draw().find("disclosure").text();
  assert.match(text, /goes to Telegram/);
  assert.match(text, /aren't end-to-end encrypted/);
  assert.match(text, /can miss some/);
});

test("once paired, setup text goes", async () => {
  const { draw } = await open(base);
  assert.equal(draw().find("disclosure"), null);
});

test("with no token, Start does nothing and the panel asks for one", async () => {
  const { draw } = await open({ ...base, token: false, running: false, paired: null });
  assert.equal(draw().find("start").press, null);
  assert.match(draw().find("token").text(), /Set token/);
});

test("the token is typed in its own terminal and never in an exec", async () => {
  const { press, asked } = await open({ ...base, token: false, running: false, paired: null });
  const opened = [];
  world.run = (name, args) => opened.push({ name, args });
  await press("token");
  assert.equal(opened[0].name, "terminal.open");
  assert.equal(opened[0].args.argv.at(-1), "token");
  assert.deepEqual(shortCalls(asked), []);
});

test("Start runs a kept background terminal, with no space labels", async () => {
  const { press } = await open({ ...base, running: false, paired: null });
  const asked = [];
  world.hc = async (args) => { asked.push(args); return reply({}); };
  await press("start");
  const args = asked[0];
  for (const flag of ["--bg", "--keep", "--no-parent", "--outlive-parent"]) assert.ok(args.includes(flag), flag);
  assert.ok(!args.some((a) => a.startsWith("herdr.")));
  assert.equal(args.at(-1), "run");
  assert.equal(args.at(-2), "/h/.config/herdr-app/mods/pageme/pageme.py");
  assert.ok(args.indexOf("--") < args.indexOf("-B"));
});

test("Windows starts python and the Mac python3", () => {
  assert.equal(logic.pythonName(true), "python");
  assert.equal(logic.pythonName(false), "python3");
  assert.ok(logic.startArgs("/a", "/h", true).includes("python"));
  assert.ok(logic.startArgs("/a", "/h", false).includes("python3"));
});

test("Stop finds the daemon by its label and ends only that", async () => {
  const { press } = await open(base, settings);
  const asked = [];
  world.hc = async (args) => { asked.push(args); return args[0] === "ls" ? reply({ terminals: [{ address: "t9" }] }) : reply({}); };
  await press("stop");
  assert.deepEqual(asked, [logic.listArgs, ["kill", "t9"], ["rm", "t9"]]);
});

test("Stop with no daemon kills nothing", async () => {
  const { press } = await open(base, settings);
  const asked = [];
  world.hc = async (args) => { asked.push(args); return reply({ terminals: [] }); };
  await press("stop");
  assert.deepEqual(asked, [logic.listArgs]);
});

test("Pair needs a running daemon", async () => {
  const stopped = await open({ ...base, running: false, paired: null });
  assert.equal(stopped.draw().find("pair").press, null);
  const running = await open({ ...base, paired: null });
  await running.press("pair");
  assert.deepEqual(shortCalls(running.asked), [["pair"]]);
});

test("a pairing code shows with its time left", async () => {
  const { draw } = await open({ ...base, paired: null, code: { value: "ABCD2345", seconds: 125 } });
  assert.equal(draw().find("code-value").text().replaceAll(" ", ""), "ABCD2345");
  assert.match(draw().find("code").text(), /2:05/);
  assert.match(draw().find("page-code").text(), /ABCD2345/);
  assert.match(draw().find("hero").text(), /Send this to your bot/);
});

test("Unpair is one press", async () => {
  const { press, asked } = await open(base, settings);
  await press("unpair");
  assert.deepEqual(shortCalls(asked), [["unpair"]]);
});

test("Pause and Resume", async () => {
  const on = await open(base, settings);
  await on.press("pause");
  assert.deepEqual(shortCalls(on.asked), [["pause"]]);
  const off = await open({ ...base, paused: true }, settings);
  await off.press("pause");
  assert.deepEqual(shortCalls(off.asked), [["resume"]]);
});

test("turning approving on takes a second press", async () => {
  const { press, asked, draw } = await open(base, settings);
  await press("approvals");
  assert.deepEqual(shortCalls(asked), []);
  assert.ok(draw().find("confirm"));
  await press("approvals-yes");
  assert.deepEqual(shortCalls(asked), [["approvals", "on"]]);
});

test("cancelling leaves approving off", async () => {
  const { press, asked, draw } = await open(base, settings);
  await press("approvals");
  await press("approvals-no");
  assert.deepEqual(shortCalls(asked), []);
  assert.equal(draw().find("confirm"), null);
});

test("pressing the switch again, or leaving Settings, cancels the confirm", async () => {
  const { press, asked, draw } = await open(base, settings);
  await press("approvals");
  await press("approvals");
  assert.equal(draw().find("confirm"), null);
  await press("approvals");
  await press("back");
  await press("gear");
  assert.equal(draw().find("confirm"), null);
  assert.deepEqual(shortCalls(asked), []);
});

test("a real panel can't open on the confirm, only a demo can", async () => {
  const real = await open(base, { ...settings, confirm: true });
  assert.equal(real.draw().find("confirm"), null);
  const demo = await open({ ...base, demo: true }, { demo: true, ...settings, confirm: true });
  assert.ok(demo.draw().find("confirm"));
});

test("turning approving off is one press", async () => {
  const { press, asked } = await open({ ...base, approvals: true }, settings);
  await press("approvals");
  assert.deepEqual(shortCalls(asked), [["approvals", "off"]]);
});

test("an answer folds into its question, and only the next line down", () => {
  const list = logic.timeline([
    { ms: 5, kind: "answered", where: "t1", text: "Dog" },
    { ms: 4, kind: "asked", where: "t1", text: "Which pet?" },
    { ms: 3, kind: "answered", where: "t2", text: "Late" },
    { ms: 2, kind: "asked", where: "t1", text: "Other?" },
  ]);
  assert.deepEqual(list.map((i) => [i.kind, i.text, i.answer]), [["answered", "Which pet?", "Dog"], ["answered", "Late", undefined], ["asked", "Other?", undefined]]);
  assert.equal(list[0].ms, 5);
});

test("recent messages show, with refusals named", async () => {
  const now = Date.now();
  const { draw } = await open({ ...base, recent: [
    { ms: now - 120000, kind: "refused", where: "t7 · demo-site", text: "That question has gone." },
    { ms: now, kind: "asked", where: "mac/t4 · sample-app", text: "Which pet?" },
  ] });
  const text = draw().find("recent").text();
  assert.match(text, /Refused/);
  assert.match(text, /2m/);
  assert.match(text, /mac\/t4/);
});

test("a Telegram problem shows", async () => {
  const { draw } = await open({ ...base, connected: false, error: "Conflict" });
  assert.equal(draw().find("note").text(), "Conflict");
});

test("a command's refusal shows", async () => {
  const { panel, cx, draw } = await open({ ...base, paired: null });
  world.exec = async (_c, args) => (args.includes("pair") ? { code: 1, stdout: "Already paired. Unpair first.", stderr: "" } : reply({ ...base, paired: null }));
  panel.short(cx, "pair");
  await cx.settled();
  assert.match(draw().find("note").text(), /Already paired/);
});

test("python missing is a plain sentence", async () => {
  world.exec = async () => { throw new Error("not found"); };
  const panel = new PageMe();
  const cx = fakeCx();
  panel.init({}, cx);
  await cx.settled();
  assert.match(panel.render().find("problem").text(), /couldn't start: not found/);
});

test("demo mode reads demo data and every control does nothing", async () => {
  const { panel, cx, asked } = await open({ ...base, demo: true }, { demo: true });
  assert.deepEqual(asked[0].args.slice(-2), ["--demo", "on-call"]);
  const before = asked.length;
  panel.short(cx, "unpair"); panel.start(cx); panel.stop(cx); panel.setToken();
  await cx.settled();
  assert.equal(asked.length, before);
});

test("a demo can name its state", async () => {
  const { asked } = await open({ ...base, demo: true }, { demo: "paused" });
  assert.deepEqual(asked[0].args.slice(-2), ["--demo", "paused"]);
});

test("the poll stops once closed", async () => {
  const { panel, cx, asked } = await open(base);
  await panel.close();
  const before = asked.length;
  cx.repeating[0].handler(cx);
  await cx.settled();
  assert.equal(asked.length, before);
});

test("small helpers", () => {
  assert.equal(logic.ago(0, 30000), "now");
  assert.equal(logic.ago(0, 3 * 3600000), "3h");
  assert.equal(logic.ago(0, 3 * 86400000), "3d");
  assert.equal(logic.codeTime(61), "1:01");
  assert.equal(logic.replyTime(45000), "45s");
  assert.equal(logic.replyTime(120000), "2m");
  assert.equal(logic.replyTime(100000), "1m 40s");
  assert.equal(logic.replyTime(5400000), "1h 30m");
  assert.equal(logic.clip("short", 70), "short");
  assert.equal(logic.daemonAddress("not json"), null);
  assert.equal(logic.readStatus({ code: 0, stdout: "nope", stderr: "" }).problem, "pageme.py printed something that isn't JSON");
});
