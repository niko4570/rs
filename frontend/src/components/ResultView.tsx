import Caveats from "./Caveats";
import SourcesList from "./SourcesList";
import type { SummaryResult } from "../types";

type Props = {
  inputName: string;
  result: SummaryResult;
  onReset: () => void;
};

export default function ResultView({ inputName, result, onReset }: Props) {
  return (
    <section className="result">
      <div className="topline">
        <span className="label">RS / RESULT</span>
        <span className="file-name" title={inputName}>
          {inputName}
        </span>
      </div>

      <h1 className="result-title">{inputName}</h1>

      <div className="section">
        <h2>Summary</h2>
        <ul className="bullets">
          {result.summary_bullets.map((bullet, index) => {
            const citations = result.citations.filter(
              (citation) => citation.bullet_index === index,
            );
            return (
              <li key={index}>
                <span>{bullet}</span>
                {citations.length > 0 && (
                  <div className="citations">
                    {citations.map((citation, citationIndex) => {
                      const sourceIndex = result.sources.findIndex(
                        (source) => source.url === citation.source_url,
                      );
                      const label =
                        sourceIndex >= 0
                          ? `Source ${sourceIndex + 1}`
                          : "Local file";
                      return (
                        <details
                          className="citation"
                          key={`${citation.source_url ?? "file"}-${citationIndex}`}
                        >
                          <summary>{label} · Evidence</summary>
                          <blockquote>{citation.excerpt}</blockquote>
                          {sourceIndex >= 0 && (
                            <a
                              href={result.sources[sourceIndex].url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {result.sources[sourceIndex].title ??
                                result.sources[sourceIndex].url}
                            </a>
                          )}
                        </details>
                      );
                    })}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      <div className="section">
        <h2>Key Details</h2>
        <div className="details">{result.key_details}</div>
      </div>

      <div className="section">
        <h2>Sources</h2>
        <SourcesList sources={result.sources} />
      </div>

      <div className="section">
        <h2>Caveats</h2>
        <Caveats caveats={result.caveats} />
      </div>

      <button type="button" className="back" onClick={onReset}>
        ← NEW RESEARCH
      </button>
    </section>
  );
}
