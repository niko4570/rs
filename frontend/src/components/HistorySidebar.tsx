import type { ResearchRecord } from "../history";

type Props = {
  records: ResearchRecord[];
  activeId: string | null;
  loading: boolean;
  disabled: boolean;
  onSelect: (record: ResearchRecord) => void;
  onDelete: (id: string) => void;
  onNew: () => void;
};

export default function HistorySidebar({
  records,
  activeId,
  loading,
  disabled,
  onSelect,
  onDelete,
  onNew,
}: Props) {
  return (
    <aside className="history-sidebar" aria-label="Research history">
      <div className="history-heading">
        <span className="label">RS / HISTORY</span>
        <button
          type="button"
          className="history-new"
          onClick={onNew}
          disabled={disabled}
        >
          + New research
        </button>
      </div>
      {loading ? (
        <p className="empty-note" role="status">
          Loading history…
        </p>
      ) : records.length === 0 ? (
        <p className="empty-note">Completed summaries will appear here.</p>
      ) : (
        <nav aria-label="Saved summaries">
          <ul className="history-list">
            {records.map((record) => (
              <li
                key={record.id}
                className={
                  activeId === record.id ? "history-row active" : "history-row"
                }
              >
                <button
                  type="button"
                  className="history-select"
                  aria-current={activeId === record.id ? "page" : undefined}
                  title={record.inputName}
                  disabled={disabled}
                  onClick={() => onSelect(record)}
                >
                  <span className="history-title">{record.inputName}</span>
                  <time dateTime={new Date(record.createdAt).toISOString()}>
                    {new Date(record.createdAt).toLocaleString()}
                  </time>
                </button>
                <button
                  type="button"
                  className="history-delete"
                  aria-label={`Delete ${record.inputName}`}
                  disabled={disabled}
                  onClick={() => onDelete(record.id)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
        </nav>
      )}
      <p className="history-note">
        Saved in this browser. Uploaded files are not stored.
      </p>
    </aside>
  );
}
