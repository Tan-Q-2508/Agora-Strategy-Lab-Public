import { Fragment, type ReactNode } from "react";

/** Render the helper's reply: paragraphs, line breaks and **bold** only (no HTML). */
export function AIText({ text }: { text: string }) {
  const paragraphs = text.split(/\n{2,}/).filter((p) => p.trim());
  return (
    <div className="flex flex-col gap-2.5 text-[15px] leading-6">
      {paragraphs.map((p, i) => (
        <p key={i} className="m-0">
          {p.split("\n").map((line, j) => (
            <Fragment key={j}>
              {j > 0 && <br />}
              {bold(line.replace(/^[-*]\s+/, "• "))}
            </Fragment>
          ))}
        </p>
      ))}
    </div>
  );
}

function bold(line: string): ReactNode[] {
  return line.split(/(\*\*[^*]+\*\*)/).map((part, k) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={k} className="font-semibold">
        {part.slice(2, -2)}
      </strong>
    ) : (
      part.replace(/^#+\s*/, "")
    ),
  );
}
