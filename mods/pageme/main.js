// The PageMe panel. It shows what the daemon is doing and runs its short commands. A mod can't host the daemon, because exec
// stops at 30 seconds, so Start runs it as a kept terminal. The token is typed into a terminal of its own, so it never passes
// through this file or an exec's arguments.
import { View } from "gpui-kit";
import { appHome, exec, hc, home, props, run } from "herdr";
import { POLL_MS, command, daemonAddress, demoName, listArgs, pythonName, readStatus, startArgs } from "./logic.js";
import { panel } from "./view.js";

export default class PageMe extends View {
  init(initial, cx) {
    const given = initial ?? props();
    this.demo = given?.demo ?? false;
    this.status = null; this.problem = null; this.note = null;
    this.busy = false; this.closed = false;
    // A demo can open straight on these, so every screen can be pictured without pressing anything.
    this.settings = given?.page === "settings"; this.confirming = Boolean(this.demo && given?.confirm);
    this.size = null; this.paths = {};
    this.refresh(cx);
    cx.timer.every(POLL_MS, (cx) => this.refresh(cx));
  }

  async close() {
    this.closed = true;
  }

  refresh(cx) {
    cx.spawn(async (cx) => {
      if (this.closed) return;
      const args = command(appHome(), "status", ...(this.demo ? ["--demo", demoName(this.demo)] : []));
      try {
        const { status, problem } = readStatus(await exec(pythonName(), args));
        this.problem = problem;
        if (status) this.status = status;
      } catch (e) {
        this.problem = `${pythonName()} couldn't start: ${e?.message ?? e}`;
      }
      cx.notify();
    });
  }

  // One short command, then a fresh look. In demo mode nothing runs.
  short(cx, ...args) {
    if (this.busy || this.demo) return;
    this.busy = true; this.note = null;
    cx.spawn(async (cx) => {
      try {
        const result = await exec(pythonName(), command(appHome(), ...args));
        if (result.code !== 0) this.note = (result.stdout + result.stderr).trim().slice(0, 200);
      } catch (e) {
        this.note = `${pythonName()} couldn't start: ${e?.message ?? e}`;
      }
      this.busy = false;
      this.refresh(cx);
    });
  }

  start(cx) {
    if (this.busy || this.demo) return;
    this.busy = true; this.note = null;
    cx.spawn(async (cx) => {
      try {
        const result = await hc(startArgs(appHome(), home()));
        if (result.code !== 0) this.note = (result.stderr || "hc run failed").trim().slice(0, 200);
      } catch (e) {
        this.note = `hc couldn't start: ${e?.message ?? e}`;
      }
      this.busy = false;
      this.refresh(cx);
    });
  }

  stop(cx) {
    if (this.busy || this.demo) return;
    this.busy = true; this.note = null;
    cx.spawn(async (cx) => {
      try {
        // Found by its label, so a terminal someone else named pageme is left alone.
        const address = daemonAddress((await hc(listArgs)).stdout);
        if (address) {
          await hc(["kill", address]);
          await hc(["rm", address]);
        }
      } catch (e) {
        this.note = `hc couldn't stop it: ${e?.message ?? e}`;
      }
      this.busy = false;
      this.refresh(cx);
    });
  }

  setToken() {
    if (this.demo) return;
    run("terminal.open", { argv: [pythonName(), ...command(appHome(), "token")], name: "PageMe token" });
  }

  // Off goes at once. On is the one setting that widens what a phone can do, so it asks first.
  approvalsPress(cx) {
    if (this.status?.approvals) {
      this.short(cx, "approvals", "off");
    } else {
      this.confirming = !this.confirming;
      cx.notify();
    }
  }

  approvalsOn(cx) {
    this.confirming = false;
    this.short(cx, "approvals", "on");
    cx.notify();
  }

  cancelConfirm(cx) {
    this.confirming = false;
    cx.notify();
  }

  openSettings(cx) {
    this.settings = true;
    cx.notify();
  }

  closeSettings(cx) {
    this.settings = false; this.confirming = false;
    cx.notify();
  }

  // In window pixels, as reported. The panel divides by the zoom when it draws, so a zoom change needs no new report.
  resized(size, cx) {
    this.size = size;
    cx.notify();
  }

  render() {
    return panel(this, Date.now());
  }
}
