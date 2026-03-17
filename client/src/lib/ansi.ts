export interface AnsiSpan {
  text: string;
  fg?: string;
  bg?: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  dim?: boolean;
}

const ANSI_COLORS_DARK: Record<number, string> = {
  30: '#3c3c3c',
  31: '#ff5f57',
  32: '#5af78e',
  33: '#f3f99d',
  34: '#57c7ff',
  35: '#ff6ac1',
  36: '#9aedfe',
  37: '#f1f1f0',
  90: '#686868',
  91: '#ff5f57',
  92: '#5af78e',
  93: '#f3f99d',
  94: '#57c7ff',
  95: '#ff6ac1',
  96: '#9aedfe',
  97: '#ffffff',
};

const ANSI_BG_COLORS: Record<number, string> = {
  40: '#3c3c3c',
  41: '#ff5f57',
  42: '#5af78e',
  43: '#f3f99d',
  44: '#57c7ff',
  45: '#ff6ac1',
  46: '#9aedfe',
  47: '#f1f1f0',
  100: '#686868',
  101: '#ff5f57',
  102: '#5af78e',
  103: '#f3f99d',
  104: '#57c7ff',
  105: '#ff6ac1',
  106: '#9aedfe',
  107: '#ffffff',
};

export function parseAnsi(text: string): AnsiSpan[] {
  const spans: AnsiSpan[] = [];
  const ansiRegex = /\x1b\[([0-9;]*)m/g;

  let lastIndex = 0;
  let currentFg: string | undefined;
  let currentBg: string | undefined;
  let bold = false;
  let italic = false;
  let underline = false;
  let dim = false;

  let match: RegExpExecArray | null;

  while ((match = ansiRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      spans.push({
        text: text.slice(lastIndex, match.index),
        fg: currentFg,
        bg: currentBg,
        bold,
        italic,
        underline,
        dim,
      });
    }

    const codes = match[1].split(';').map(Number);

    let i = 0;
    while (i < codes.length) {
      const code = codes[i];

      if (code === 0) {
        currentFg = undefined;
        currentBg = undefined;
        bold = false;
        italic = false;
        underline = false;
        dim = false;
      } else if (code === 1) {
        bold = true;
      } else if (code === 2) {
        dim = true;
      } else if (code === 3) {
        italic = true;
      } else if (code === 4) {
        underline = true;
      } else if (code === 22) {
        bold = false;
        dim = false;
      } else if (code === 23) {
        italic = false;
      } else if (code === 24) {
        underline = false;
      } else if (ANSI_COLORS_DARK[code]) {
        currentFg = ANSI_COLORS_DARK[code];
      } else if (ANSI_BG_COLORS[code]) {
        currentBg = ANSI_BG_COLORS[code];
      } else if (code === 38) {
        if (codes[i + 1] === 5) {
          currentFg = get256Color(codes[i + 2]);
          i += 2;
        } else if (codes[i + 1] === 2) {
          currentFg = `rgb(${codes[i + 2]},${codes[i + 3]},${codes[i + 4]})`;
          i += 4;
        }
      } else if (code === 48) {
        if (codes[i + 1] === 5) {
          currentBg = get256Color(codes[i + 2]);
          i += 2;
        } else if (codes[i + 1] === 2) {
          currentBg = `rgb(${codes[i + 2]},${codes[i + 3]},${codes[i + 4]})`;
          i += 4;
        }
      } else if (code === 39) {
        currentFg = undefined;
      } else if (code === 49) {
        currentBg = undefined;
      }

      i++;
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    spans.push({
      text: text.slice(lastIndex),
      fg: currentFg,
      bg: currentBg,
      bold,
      italic,
      underline,
      dim,
    });
  }

  return spans;
}

function get256Color(n: number): string {
  if (n < 16) {
    const basic: Record<number, string> = {
      0: '#000000', 1: '#800000', 2: '#008000', 3: '#808000',
      4: '#000080', 5: '#800080', 6: '#008080', 7: '#c0c0c0',
      8: '#808080', 9: '#ff0000', 10: '#00ff00', 11: '#ffff00',
      12: '#0000ff', 13: '#ff00ff', 14: '#00ffff', 15: '#ffffff',
    };
    return basic[n] || '#ffffff';
  }
  if (n < 232) {
    const idx = n - 16;
    const r = Math.floor(idx / 36) * 51;
    const g = Math.floor((idx % 36) / 6) * 51;
    const b = (idx % 6) * 51;
    return `rgb(${r},${g},${b})`;
  }
  const gray = (n - 232) * 10 + 8;
  return `rgb(${gray},${gray},${gray})`;
}

export function stripAnsi(text: string): string {
  return text.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '');
}
