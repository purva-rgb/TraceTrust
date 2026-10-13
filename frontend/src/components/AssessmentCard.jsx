import { leadingScore } from "../fusion.js";

function hasDeviceBurst(assessment) {
  const groups = [...(assessment?.hypotheses || []), assessment?.leading];
  return groups.some((item) =>
    (item?.reasons || []).some((reason) => String(reason).includes("distinct registered devices")),
  );
}

export default function AssessmentCard({ assessment, flagged = false }) {
  const lead = leadingScore(assessment);
  const points = flagged ? 100 : lead.points;
  const note =
    points === 5
      ? "too many scans from same user"
      : hasDeviceBurst(assessment)
        ? "multiple devices detected"
        : "";

  return (
    <article className="card">
      <h3>Confidence score</h3>
      <p className="score-line">
        <strong>{points}/100</strong>
      </p>
      {note ? <p>{note}</p> : null}
    </article>
  );
}
