import { Fragment } from "react";

function applyInline(text: string) {
  const nodes: React.ReactNode[] = [];
  const pattern = /\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }

    if (match[1] && match[2]) {
      nodes.push(
        <a
          key={`${match.index}-link`}
          href={match[2]}
          target={match[2].startsWith("http") ? "_blank" : undefined}
          rel="noreferrer"
        >
          {match[1]}
        </a>,
      );
    } else if (match[3]) {
      nodes.push(<strong key={`${match.index}-bold`}>{match[3]}</strong>);
    } else if (match[4]) {
      nodes.push(<code key={`${match.index}-code`}>{match[4]}</code>);
    }

    lastIndex = pattern.lastIndex;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}

export function Markdown({ content }: { content: string }) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const output: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i += 1;
      continue;
    }

    if (line.startsWith("```")) {
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      output.push(
        <pre key={`pre-${i}`}>
          <code>{code.join("\n")}</code>
        </pre>,
      );
      i += 1;
      continue;
    }

    if (/^---+$/.test(line.trim())) {
      output.push(<hr key={`hr-${i}`} />);
      i += 1;
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const level = heading[1].length;
      const text = heading[2].trim();
      if (level === 1) output.push(<h1 key={`h1-${i}`}>{applyInline(text)}</h1>);
      else if (level === 2) output.push(<h2 key={`h2-${i}`}>{applyInline(text)}</h2>);
      else if (level === 3) output.push(<h3 key={`h3-${i}`}>{applyInline(text)}</h3>);
      else output.push(<h4 key={`h4-${i}`}>{applyInline(text)}</h4>);
      i += 1;
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*]\s+/, ""));
        i += 1;
      }
      output.push(
        <ul key={`ul-${i}`}>
          {items.map((item, index) => (
            <li key={`${i}-${index}`}>{applyInline(item)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s+/, ""));
        i += 1;
      }
      output.push(
        <ol key={`ol-${i}`}>
          {items.map((item, index) => (
            <li key={`${i}-${index}`}>{applyInline(item)}</li>
          ))}
        </ol>,
      );
      continue;
    }

    const paragraph: string[] = [line.trim()];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].startsWith("#") &&
      !/^[-*]\s+/.test(lines[i]) &&
      !/^\d+\.\s+/.test(lines[i]) &&
      !lines[i].startsWith("```") &&
      !/^---+$/.test(lines[i].trim())
    ) {
      paragraph.push(lines[i].trim());
      i += 1;
    }

    output.push(<p key={`p-${i}`}>{applyInline(paragraph.join(" "))}</p>);
  }

  return <Fragment>{output}</Fragment>;
}
