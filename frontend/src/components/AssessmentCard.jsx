import { leadingScore } from "../fusion.js";

export default function AssessmentCard({ assessment, flagged = false }) {
  const lead = leadingScore(assessment);
  const points = flagged ? 100 : lead.points;

  return (
    <article className="card">
      <h3>Confidence score</h3>
      <p className="score-line">
        <strong>{points}/100</strong>
      </p>
    </article>
  );
}
