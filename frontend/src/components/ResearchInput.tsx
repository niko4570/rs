import { useState, type DragEvent, type KeyboardEvent } from "react";
import FileDropzone from "./FileDropzone";

const SUPPORTED_EXTENSIONS = [".txt", ".md", ".markdown"] as const;

function isSupportedFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return SUPPORTED_EXTENSIONS.some((extension) => name.endsWith(extension));
}

type Props = {
  text: string;
  onTextChange: (value: string) => void;
  file: File | null;
  onFileChange: (file: File | null) => void;
  onSubmit: () => void;
  disabled: boolean;
};

export default function ResearchInput({
  text,
  onTextChange,
  file,
  onFileChange,
  onSubmit,
  disabled,
}: Props) {
  const [isDragging, setIsDragging] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  const hasInput = file !== null || text.trim().length > 0;
  const submitDisabled = disabled || !hasInput;

  const acceptFile = (candidate: File | null) => {
    if (candidate && !isSupportedFile(candidate)) {
      setFileError(
        `Unsupported file type. Use ${SUPPORTED_EXTENSIONS.join(", ")} files.`,
      );
      onFileChange(null);
      return;
    }
    setFileError(null);
    onFileChange(candidate);
  };

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!disabled) {
      setIsDragging(true);
    }
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    if (disabled) {
      return;
    }
    acceptFile(event.dataTransfer.files?.[0] ?? null);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      if (!submitDisabled) {
        onSubmit();
      }
    }
  };

  return (
    <section className="hero">
      <div className="eyebrow">LOCAL RESEARCH</div>
      <h1>Understand what you&rsquo;re reading.</h1>
      <div className="lead">
        Drop a file, paste a URL, or ask a research question. rs turns the input
        into a concise, evidence-grounded summary.
      </div>

      <div
        className={`input-box${isDragging ? " drag" : ""}`}
        onDragEnter={handleDragOver}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <textarea
          value={text}
          onChange={(event) => onTextChange(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled || file !== null}
          placeholder={
            file
              ? "File selected — click SUMMARIZE to analyze it."
              : "Ask a question, paste a URL, or drop a .md / .txt file here..."
          }
        />
        <div className="toolbar">
          <FileDropzone file={file} onSelect={acceptFile} disabled={disabled} />
          <div className="actions">
            <span className="hint">⌘ / CTRL + ENTER</span>
            <button
              type="button"
              className="primary"
              onClick={onSubmit}
              disabled={submitDisabled}
            >
              SUMMARIZE →
            </button>
          </div>
        </div>
        {fileError && <div className="file-error">{fileError}</div>}
      </div>

      <div className="drop-note">
        or drag a local document anywhere into the box
      </div>

      <div className="meta">
        <span>LOCAL-FIRST</span>
        <span>EVIDENCE GROUNDED</span>
        <span>ONE-PASS SYNTHESIS</span>
      </div>
    </section>
  );
}
