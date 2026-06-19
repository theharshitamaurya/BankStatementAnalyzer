import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const port = process.env.PORT || "8765";
const url = `http://127.0.0.1:${port}/`;
const bundledPython = String.raw`C:\Users\HP\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`;
const pythonExe = process.env.HDFC_PYTHON_EXE || (fs.existsSync(bundledPython) ? bundledPython : "python");

function openBrowser() {
  if (process.platform === "win32") {
    spawn("cmd", ["/c", "start", "", url], { detached: true, stdio: "ignore" }).unref();
  } else if (process.platform === "darwin") {
    spawn("open", [url], { detached: true, stdio: "ignore" }).unref();
  } else {
    spawn("xdg-open", [url], { detached: true, stdio: "ignore" }).unref();
  }
}

console.log(`Bank Statement Analyzer dev server`);
console.log(`URL: ${url}`);
console.log(`Python: ${pythonExe}`);

const server = spawn(pythonExe, [path.join(root, "app", "server.py")], {
  cwd: root,
  env: {
    ...process.env,
    PORT: port,
    HDFC_PYTHON_EXE: pythonExe,
  },
  stdio: "inherit",
});

if (process.argv.includes("--open")) {
  setTimeout(openBrowser, 1500);
}

server.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    server.kill(signal);
  });
}
