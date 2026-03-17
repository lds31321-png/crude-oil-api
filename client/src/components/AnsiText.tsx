import { parseAnsi, type AnsiSpan } from "@/lib/ansi";

interface AnsiTextProps {
  text: string;
}

function SpanRenderer({ span }: { span: AnsiSpan }) {
  const style: React.CSSProperties = {};
  if (span.fg) style.color = span.fg;
  if (span.bg) style.backgroundColor = span.bg;
  if (span.bold) style.fontWeight = 'bold';
  if (span.italic) style.fontStyle = 'italic';
  if (span.underline) style.textDecoration = 'underline';
  if (span.dim) style.opacity = 0.5;

  if (Object.keys(style).length === 0) {
    return <span>{span.text}</span>;
  }

  return <span style={style}>{span.text}</span>;
}

export function AnsiText({ text }: AnsiTextProps) {
  const spans = parseAnsi(text);
  return (
    <>
      {spans.map((span, i) => (
        <SpanRenderer key={i} span={span} />
      ))}
    </>
  );
}
