// Subscribe to a workspace's live pipeline events and print them (used by smoke.sh).
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "../frontend/package.json"));
const { io } = require("socket.io-client");

const [api, token, workspaceId] = process.argv.slice(2);
const socket = io(api, { auth: { token }, transports: ["websocket"] });
socket.on("connect", () => {
  socket.emit("subscribe", { workspace_id: workspaceId }, (ack) => console.log("subscribed", JSON.stringify(ack)));
});
socket.on("connect_error", (err) => console.error("connect_error", err.message));
socket.on("meeting:progress", (ev) => console.log("meeting:progress", JSON.stringify(ev)));
setTimeout(() => process.exit(0), 120_000);
