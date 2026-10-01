import type { Source } from "../types";

type Props = {
  sources: Source[];
};

export default function SourcesList({ sources }: Props) {
  if (sources.length === 0) {
    return (
      <div className="empty-note">
        No sources were returned for this request.
      </div>
    );
  }

  return (
    <div>
      {sources.map((source, index) => (
        <div className="source" key={`${source.url}-${index}`}>
          <div className="num">{String(index + 1).padStart(2, "0")}</div>
          <div>
            <div className="source-title">{source.title ?? source.url}</div>
            <a
              className="source-url"
              href={source.url}
              target="_blank"
              rel="noreferrer"
            >
              {source.url}
            </a>
          </div>
        </div>
      ))}
    </div>
  );
}
