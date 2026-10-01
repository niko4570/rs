import { useEffect, useState } from "react";

const STEPS = [
  { name: "INPUT", detail: "Reading your research input..." },
  { name: "EVIDENCE", detail: "Collecting relevant material..." },
  { name: "SYNTHESIZE", detail: "Generating structured summary..." },
];

type Props = {
  inputName: string;
};

export default function ProcessingView({ inputName }: Props) {
  const [active, setActive] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setActive((current) => Math.min(current + 1, STEPS.length - 1));
    }, 1400);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <section className="progress">
      <div className="topline">
        <span className="label">RS / PROCESSING</span>
        <span className="file-name" title={inputName}>
          {inputName}
        </span>
      </div>
      <div className="steps">
        {STEPS.map((step, index) => (
          <div
            key={step.name}
            className={`step${index === active ? " active" : ""}`}
          >
            <div className="step-name">{step.name}</div>
            <div className="step-detail">{step.detail}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
