import { type ChangeEvent, type MouseEvent } from "react";

type Props = {
  file: File | null;
  onSelect: (file: File | null) => void;
  disabled?: boolean;
};

export default function FileDropzone({
  file,
  onSelect,
  disabled = false,
}: Props) {
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    onSelect(event.target.files?.[0] ?? null);
    // Reset so selecting the same file again still fires a change event.
    event.target.value = "";
  };

  const handleClear = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onSelect(null);
  };

  return (
    <span className="file-control">
      <label className={`file-label${disabled ? " disabled" : ""}`}>
        <span>＋</span>
        <span className="file-name-text" title={file?.name}>
          {file ? file.name.toUpperCase() : "ADD FILE"}
        </span>
        <input
          type="file"
          accept=".txt,.md,.markdown"
          disabled={disabled}
          onChange={handleChange}
        />
      </label>
      {file && !disabled && (
        <button
          type="button"
          className="file-clear"
          onClick={handleClear}
          aria-label="Remove file"
        >
          ×
        </button>
      )}
    </span>
  );
}
