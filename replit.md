# Shell — Web Terminal Emulator

A beautiful, fully functional web-based terminal emulator built with React + Express + WebSockets.

## Features

- **Real shell execution** — Commands are executed on the server via WebSocket
- **Multiple tabs** — Open unlimited terminal sessions simultaneously
- **ANSI color support** — Full 256-color ANSI escape code rendering
- **Command history** — Navigate with Up/Down arrow keys
- **cd navigation** — Full directory traversal with cwd tracking
- **Keyboard shortcuts** — Ctrl+C, Ctrl+L, Ctrl+T
- **Font size control** — Adjustable via settings panel
- **Stunning terminal UI** — macOS-style traffic lights, green status bar

## Architecture

- **Frontend**: React + TanStack Query + Wouter + Tailwind CSS
- **Backend**: Express + WebSocket Server (`ws`)
- **Shell**: Commands run via `child_process.exec` per session
- **Theme**: Dark terminal theme with green accent (`hsl(142 71% 45%)`)

## Project Structure

```
client/src/
  pages/Terminal.tsx      — Main terminal page (tabs, I/O, input)
  components/AnsiText.tsx — ANSI escape code renderer
  lib/ansi.ts             — ANSI parser utility
  index.css               — Dark terminal theme

server/
  routes.ts               — WebSocket shell session handler
  index.ts                — Express + HTTP server setup
```

## Key Technical Decisions

- Commands are executed per-request (not a persistent PTY session) for simplicity and reliability
- `cd` is handled specially to maintain CWD state across commands
- ANSI colors parsed client-side from raw escape sequences
- WebSocket auto-reconnects on disconnect
- Each tab creates its own WebSocket connection with independent CWD state
