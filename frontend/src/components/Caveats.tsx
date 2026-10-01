type Props = {
  caveats: string[];
};

export default function Caveats({ caveats }: Props) {
  if (caveats.length === 0) {
    return (
      <div className="empty-note">
        No caveats were reported for this request.
      </div>
    );
  }

  return (
    <ul className="bullets">
      {caveats.map((caveat, index) => (
        <li key={index}>{caveat}</li>
      ))}
    </ul>
  );
}
