/**
 * Markdown answer renderer. Citation markers like [1] become chips that show the source title on hover and
 * link to it. Raw HTML is not rendered; external links open safely in a new tab.
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Source } from "../lib/types";
import { cx } from "./ui";

/** "[1][2]" -> markdown links "#cite-1" that the custom <a> renders as chips. */
export function linkCitations(text: string): string {
  return text.replace(/\[(\d{1,3})\](?!\()/g, "[$1](#cite-$1)");
}

/**
 * The sources to show as cards under an answer: only the ones it cites, in citation order - a refusal cites
 * nothing, so it shows no (irrelevant) sources. Duplicates are removed per section (title + url), not per
 * article - several sections of one article are different sources.
 */
export function citedSources(answer: string, sources: Source[]): Source[] {
  const numbered = sources.map((s, i) => ({ ...s, n: s.n ?? i + 1 }));
  const cited = [...new Set([...answer.matchAll(/\[(\d{1,3})\](?!\()/g)].map((m) => Number(m[1])))];
  const picked = cited.map((n) => numbered.find((s) => s.n === n)).filter((s): s is (typeof numbered)[number] => !!s);
  const seen = new Set<string>();
  return picked.filter((s) => {
    const key = `${s.title ?? ""}|${s.url ?? ""}`;
    return s.url && !seen.has(key) && seen.add(key);
  });
}

export function Markdown({ text, sources = [], className }: { text: string; sources?: Source[]; className?: string }) {
  const byN = new Map(sources.map((s, i) => [s.n ?? i + 1, s]));
  return (
    <div className={cx("prose prose-sm prose-slate max-w-none prose-p:my-2 prose-li:my-0.5 prose-headings:mt-3", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const cite = href?.match(/^#cite-(\d+)$/);
            if (cite) {
              const src = byN.get(Number(cite[1]));
              return (
                <a href={src?.url ?? undefined} target="_blank" rel="noopener noreferrer" title={src?.title ?? `Source ${cite[1]}`}
                  className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-brand-100 px-1 align-text-top text-[10px] font-semibold text-brand-700 no-underline hover:bg-brand-500 hover:text-white">
                  {cite[1]}
                </a>
              );
            }
            return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
          },
        }}
      >
        {linkCitations(text)}
      </ReactMarkdown>
    </div>
  );
}
