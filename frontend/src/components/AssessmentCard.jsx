import { supportPoints } from "../fusion.js";

export default function AssessmentCard({ assessment }) {
  if (!assessment) return null;
  const hypotheses = (assessment.hypotheses || []).filter(
    (item) => item.cause !== "PROCESS_RECORDING_GAP" && item.support_score > 0,
  );
  const process = assessment.process_recording_gap;
  const showProcess = process?.has_documentation_gap;
  const processFields = new Set([
    "quantity",
    "shipment_ref",
    "signature",
    "product_uid",
    "event_time_ms",
    "independent_corroboration",
  ]);
  const missing = assessment.missing_checks || [];
  const processMissing = missing.filter((item) => processFields.has(item));
  const otherMissing = missing.filter((item) => !processFields.has(item));
  const showSuspicious =
    hypotheses.length > 0 || otherMissing.length > 0 || assessment.requires_investigator_review;
  if (!hypotheses.length && !showProcess && !missing.length && !assessment.requires_investigator_review) return null;
  return (
    <>
      {showProcess ? (
        <article className="card">
          <h3>
            Process / recording gap
            {assessment.is_simulated ? <span className="sim-badge">simulated</span> : null}
          </h3>
          <p>
            <strong>
              Process/recording gap: {process.support_points ?? supportPoints(process.support_score)}/100 explanation
              support.
            </strong>{" "}
            Documentation incomplete{process.requires_investigator_review ? ", investigator review required." : "."}
          </p>
          {process.outcome === "INSUFFICIENT_EVIDENCE" ? <p className="muted">Insufficient evidence</p> : null}
          {processMissing.length ? (
            <ul className="flags">
              {processMissing.map((item) => (
                <li key={item}>
                  <span>{item}</span>
                  <strong className="not-checked">NOT_CHECKED</strong>
                </li>
              ))}
            </ul>
          ) : null}
        </article>
      ) : null}
      {showSuspicious ? (
        <article className="card">
          <h3>
            Evidence assessment
            {assessment.is_simulated ? <span className="sim-badge">simulated</span> : null}
          </h3>
          {assessment.outcome === "INSUFFICIENT_EVIDENCE" ? <p>Insufficient evidence</p> : null}
          {assessment.outcome === "AMBIGUOUS" ? <p>Ambiguous — the top two causes are too close to separate.</p> : null}
          {hypotheses.map((item) => (
            <p key={item.cause}>
              <strong>
                {item.label || item.cause}: {item.support_points ?? supportPoints(item.support_score)}/100 evidence support
              </strong>
            </p>
          ))}
          {hypotheses.flatMap((item) => item.reasons || []).map((reason) => (
            <p key={reason} className="muted">
              {reason}
            </p>
          ))}
          {otherMissing.length ? (
            <ul className="flags">
              {otherMissing.map((item) => (
                <li key={item}>
                  <span>{item}</span>
                  <strong className="not-checked">NOT_CHECKED</strong>
                </li>
              ))}
            </ul>
          ) : null}
          {assessment.requires_investigator_review ? <p>requires investigator review</p> : null}
        </article>
      ) : null}
    </>
  );
}
