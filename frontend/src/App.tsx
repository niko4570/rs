import { useCallback, useEffect, useRef, useState } from "react";
import { researchFile, researchTopic, researchUrl } from "./api";
import HistorySidebar from "./components/HistorySidebar";
import {
  deleteRecord,
  loadHistory,
  saveRecord,
  type ResearchRecord,
} from "./history";
import ProcessingView from "./components/ProcessingView";
import ResearchInput from "./components/ResearchInput";
import ResultView from "./components/ResultView";
import type { SummaryResult } from "./types";

type AppState =
  | { status: "idle" }
  | { status: "processing"; inputName: string }
  | { status: "success"; result: SummaryResult; inputName: string }
  | { status: "error"; message: string };

const LONE_URL_PATTERN = /^https?:\/\/\S+$/i;

export default function App() {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [state, setState] = useState<AppState>({ status: "idle" });
  const submitting = useRef(false);
  const deleting = useRef(false);
  const [records, setRecords] = useState<ResearchRecord[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyDeleting, setHistoryDeleting] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    loadHistory()
      .then((saved) => {
        if (!cancelled) setRecords(saved);
      })
      .catch(() => {
        if (!cancelled)
          setHistoryError(
            "Could not load history. Browser storage may be unavailable. You can still create summaries.",
          );
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = useCallback(async () => {
    if (submitting.current || deleting.current || historyLoading) {
      return;
    }

    const trimmed = text.trim();
    if (!file && !trimmed) {
      return;
    }

    submitting.current = true;
    const inputName = file ? file.name : trimmed;
    const inputType = file
      ? "file"
      : LONE_URL_PATTERN.test(trimmed)
        ? "url"
        : "topic";
    setActiveId(null);
    setState({ status: "processing", inputName });

    try {
      let result: SummaryResult;
      if (file) {
        result = await researchFile(file);
      } else if (LONE_URL_PATTERN.test(trimmed)) {
        result = await researchUrl(trimmed);
      } else {
        result = await researchTopic(trimmed);
      }
      try {
        const record: ResearchRecord = {
          id: crypto.randomUUID(),
          createdAt: Date.now(),
          inputType,
          inputName,
          result,
        };
        await saveRecord(record);
        setRecords((previous) => [record, ...previous]);
        setActiveId(record.id);
        setHistoryError(null);
      } catch {
        setHistoryError(
          "This summary could not be saved. It is still shown below, but will be lost when you leave or reload. Browser storage may be unavailable or full.",
        );
      }
      setState({ status: "success", result, inputName });
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "An unexpected error occurred. Please try again.";
      setState({ status: "error", message });
    } finally {
      submitting.current = false;
    }
  }, [file, text, historyLoading]);

  const handleReset = useCallback(() => {
    if (submitting.current || deleting.current) return;
    setText("");
    setFile(null);
    setActiveId(null);
    setState({ status: "idle" });
  }, []);

  const handleSelect = (record: ResearchRecord) => {
    if (submitting.current || deleting.current) return;
    setText("");
    setFile(null);
    setActiveId(record.id);
    setState({
      status: "success",
      inputName: record.inputName,
      result: record.result,
    });
  };

  const handleDelete = async (id: string) => {
    if (submitting.current || deleting.current) return;
    deleting.current = true;
    setHistoryDeleting(true);
    try {
      await deleteRecord(id);
      setRecords((previous) => previous.filter((record) => record.id !== id));
      if (activeId === id) {
        setActiveId(null);
        setText("");
        setFile(null);
        setState({ status: "idle" });
      }
      setHistoryError(null);
    } catch {
      setHistoryError(
        "Could not delete this summary. The record has been kept; please try again.",
      );
    } finally {
      deleting.current = false;
      setHistoryDeleting(false);
    }
  };

  return (
    <div className="app">
      <HistorySidebar
        records={records}
        activeId={activeId}
        loading={historyLoading}
        disabled={
          historyLoading || historyDeleting || state.status === "processing"
        }
        onSelect={handleSelect}
        onDelete={handleDelete}
        onNew={handleReset}
      />
      <main>
        {historyError && (
          <p className="storage-error" role="alert">
            {historyError}
          </p>
        )}
        {state.status === "idle" && (
          <ResearchInput
            text={text}
            onTextChange={setText}
            file={file}
            onFileChange={setFile}
            onSubmit={handleSubmit}
            disabled={historyLoading || historyDeleting}
          />
        )}

        {state.status === "processing" && (
          <ProcessingView inputName={state.inputName} />
        )}

        {state.status === "success" && (
          <ResultView
            inputName={state.inputName}
            result={state.result}
            onReset={handleReset}
          />
        )}

        {state.status === "error" && (
          <section className="error">
            <div className="topline">
              <span className="label">RS / ERROR</span>
            </div>
            <div className="error-panel">
              <h2 className="error-title">
                Could not complete this research request.
              </h2>
              <p className="error-message">{state.message}</p>
            </div>
            <button type="button" className="back" onClick={handleReset}>
              ← NEW RESEARCH
            </button>
          </section>
        )}
      </main>
    </div>
  );
}
