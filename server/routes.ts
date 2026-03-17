import type { Express } from "express";
import { createServer, type Server } from "http";
import { WebSocketServer, type WebSocket } from "ws";
import { storage } from "./storage";

interface ShellSession {
  ws: WebSocket;
  cwd: string;
  currentExec: ReturnType<typeof import('child_process').exec> | null;
}

function getCwdDisplay(cwd: string): string {
  const home = process.env.HOME || '/root';
  if (cwd.startsWith(home)) {
    return '~' + cwd.slice(home.length);
  }
  return cwd;
}

export async function registerRoutes(
  httpServer: Server,
  app: Express
): Promise<Server> {
  const wss = new WebSocketServer({ server: httpServer, path: '/ws/shell' });

  wss.on('connection', (ws: WebSocket) => {
    const session: ShellSession = {
      ws,
      cwd: process.env.HOME || process.cwd(),
      currentExec: null,
    };

    ws.send(JSON.stringify({ type: 'cwd', data: getCwdDisplay(session.cwd) }));

    ws.on('message', (raw) => {
      try {
        const msg = JSON.parse(raw.toString());

        if (msg.type === 'command') {
          const command = (msg.data as string).trim();

          if (!command) {
            ws.send(JSON.stringify({ type: 'cwd', data: getCwdDisplay(session.cwd) }));
            return;
          }

          if (command === 'clear') {
            ws.send(JSON.stringify({ type: 'clear' }));
            ws.send(JSON.stringify({ type: 'cwd', data: getCwdDisplay(session.cwd) }));
            return;
          }

          const cdMatch = command.match(/^cd\s*(.*)$/);
          if (cdMatch) {
            const targetRaw = cdMatch[1].trim() || (process.env.HOME || '~');
            const target = targetRaw === '~'
              ? (process.env.HOME || '/root')
              : targetRaw.startsWith('~/')
                ? (process.env.HOME || '/root') + targetRaw.slice(1)
                : targetRaw.startsWith('/')
                  ? targetRaw
                  : `${session.cwd}/${targetRaw}`;

            const { execSync } = require('child_process');
            try {
              const resolved = execSync(`cd "${target}" && pwd`, {
                cwd: session.cwd,
                encoding: 'utf8',
                env: { ...process.env, HOME: process.env.HOME || '/root' },
              }).trim();
              session.cwd = resolved;
              ws.send(JSON.stringify({ type: 'cwd', data: getCwdDisplay(session.cwd) }));
            } catch (err: any) {
              ws.send(JSON.stringify({ type: 'error', data: `cd: ${err.stderr || err.message}\n` }));
              ws.send(JSON.stringify({ type: 'cwd', data: getCwdDisplay(session.cwd) }));
            }
            return;
          }

          if (command === 'help') {
            const helpText = [
              '\x1b[32mAvailable built-in commands:\x1b[0m',
              '',
              '\x1b[33mNavigation:\x1b[0m',
              '  \x1b[36mcd\x1b[0m [dir]     Change directory',
              '  \x1b[36mpwd\x1b[0m          Print working directory',
              '  \x1b[36mls\x1b[0m [flags]   List directory contents',
              '',
              '\x1b[33mFile Operations:\x1b[0m',
              '  \x1b[36mcat\x1b[0m [file]   Display file contents',
              '  \x1b[36mecho\x1b[0m [text]  Print text',
              '  \x1b[36mmkdir\x1b[0m [dir]  Create directory',
              '  \x1b[36mtouch\x1b[0m [file] Create empty file',
              '  \x1b[36mrm\x1b[0m [file]    Remove file',
              '  \x1b[36mcp\x1b[0m src dst   Copy files',
              '  \x1b[36mmv\x1b[0m src dst   Move files',
              '',
              '\x1b[33mSystem:\x1b[0m',
              '  \x1b[36mclear\x1b[0m        Clear terminal',
              '  \x1b[36mwhoami\x1b[0m       Current user',
              '  \x1b[36mdate\x1b[0m         Current date',
              '  \x1b[36mps\x1b[0m           Process list',
              '',
              '\x1b[33mKeyboard Shortcuts:\x1b[0m',
              '  \x1b[90mCtrl+C\x1b[0m      Interrupt',
              '  \x1b[90mCtrl+L\x1b[0m      Clear screen',
              '  \x1b[90mCtrl+T\x1b[0m      New tab',
              '  \x1b[90m↑ / ↓\x1b[0m       Command history',
            ].join('\n');
            ws.send(JSON.stringify({ type: 'output', data: helpText + '\n' }));
            ws.send(JSON.stringify({ type: 'cwd', data: getCwdDisplay(session.cwd) }));
            return;
          }

          const { exec } = require('child_process');
          session.currentExec = exec(
            command,
            {
              cwd: session.cwd,
              env: {
                ...process.env,
                TERM: 'xterm-256color',
                COLORTERM: 'truecolor',
                FORCE_COLOR: '3',
                CLICOLOR_FORCE: '1',
                LS_COLORS: 'rs=0:di=01;34:ln=01;36:pi=40;33:so=01;35:do=01;35:bd=40;33;01:cd=40;33;01:or=40;31;01:su=37;41:sg=30;43:tw=30;42:ow=34;42:st=37;44:ex=01;32:',
                HOME: process.env.HOME || '/root',
              },
              maxBuffer: 10 * 1024 * 1024,
              timeout: 30000,
            },
            (error: any, stdout: string, stderr: string) => {
              if (stdout) {
                ws.send(JSON.stringify({ type: 'output', data: stdout }));
              }
              if (stderr) {
                ws.send(JSON.stringify({ type: 'error', data: stderr }));
              }
              if (error && !stdout && !stderr) {
                ws.send(JSON.stringify({ type: 'error', data: `Command failed: ${error.message}\n` }));
              }
              ws.send(JSON.stringify({ type: 'cwd', data: getCwdDisplay(session.cwd) }));
            }
          );
        } else if (msg.type === 'interrupt') {
          if (session.currentExec) {
            try { (session.currentExec as any).kill('SIGINT'); } catch {}
            session.currentExec = null;
          }
          ws.send(JSON.stringify({ type: 'output', data: '^C\n' }));
          ws.send(JSON.stringify({ type: 'cwd', data: getCwdDisplay(session.cwd) }));
        }
      } catch (err) {
        console.error('WebSocket message error:', err);
      }
    });

    ws.on('close', () => {
      session.currentExec = null;
    });
  });

  return httpServer;
}
