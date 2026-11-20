// The desktop icon on your own Windows PC. The launcher (start.ps1) starts Freefield with FREEFIELD_DESKTOP_ICON=1;
// the studio then asks once whether to put an icon on the desktop. It cannot make one itself (it runs in Linux, in the
// container), so it keeps the answer in the volume and the launcher's window, still open on Windows, makes the icon
// and writes back "created". Never on RunPod, Vast.ai or the hosted demo: nothing sets FREEFIELD_DESKTOP_ICON there.
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

/** ask: nobody answered yet; wanted: yes, the launcher is about to make it; created; declined. */
export type IconState = "ask" | "wanted" | "created" | "declined";

export class DesktopIcon {
  readonly file: string | null;
  constructor(file: string | null) {   // a plain field: Node's type stripping takes no parameter properties
    this.file = file;
  }

  static fromEnv(env: NodeJS.ProcessEnv = process.env): DesktopIcon {
    return new DesktopIcon(env.FREEFIELD_DESKTOP_ICON === "1" ? join(env.FREEFIELD_DATA || "/workspace/freefield", "desktop-icon") : null);
  }

  /** null where there is no launcher to make the icon */
  state(): IconState | null {
    if (!this.file) return null;
    try {
      const v = readFileSync(this.file, "utf-8").trim();
      if (v === "wanted" || v === "created" || v === "declined") return v;
    } catch { /* not answered yet */ }
    return "ask";
  }

  answer(want: boolean): IconState | null {
    if (!this.file) return null;
    if (this.state() === "created") return "created";
    writeFileSync(this.file, want ? "wanted" : "declined");
    return want ? "wanted" : "declined";
  }
}
