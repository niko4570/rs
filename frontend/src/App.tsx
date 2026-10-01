import { useCallback, useRef, useState } from "react";
import { researchFile, researchTopic, researchUrl } from "./api";
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

  const handleSubmit = useCallback(async () => {
    if (submitting.current) {
      return;
    }

    const trimmed = text.trim();
    if (!file && !trimmed) {
      return;
    }

    submitting.current = true;
    const inputName = file ? file.name : trimmed;
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
  }, [file, text]);

  const handleReset = useCallback(() => {
    setText("");
    setFile(null);
    setState({ status: "idle" });
  }, []);

  return (
    <div className="app">
      <main>
        {state.status === "idle" && (
          <ResearchInput
            text={text}
            onTextChange={setText}
            file={file}
            onFileChange={setFile}
            onSubmit={handleSubmit}
            disabled={false}
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
