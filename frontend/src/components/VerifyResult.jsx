import { eventPoints } from "../gps.js";
import AssessmentCard from "./AssessmentCard.jsx";
import GpsMap from "./GpsMap.jsx";

function formatFlag(value) {
  if (value === true) return "yes";
  if (value === false) return "no";
  return String(value);
}

function physicalLine(physical, key) {
  const status = physical[key] || "NOT_CHECKED";
  if (key === "box_id" && physical.box_serial) return `${physical.box_serial} · ${status}`;
  if (key === "seal_id" && physical.seal_serial) return `${physical.seal_serial} · ${status}`;
  return status;
}

function FlagList({ flags }) {
  if (!flags) return <p className="muted">restriction_flags unavailable</p>;
  return (
    <ul className="flags">
      {Object.entries(flags).map(([key, value]) => (
        <li key={key}>
          <span>{key}</span>
          <strong>{formatFlag(value)}</strong>
        </li>
      ))}
    </ul>
  );
}

export default function VerifyResult({ result, full = false }) {
  if (!result) return null;
  const headline = (result.headline || "").toLowerCase().includes("genuine")
    ? "Digital record verified"
    : result.headline;
  const integrity = result.record_integrity || {};
  const physical = result.physical_checks || {};
  const points = eventPoints(result.events);

  return (
    <section className="stack">
      <div className={`banner status-${(result.final_status || "UNKNOWN").toLowerCase()}`}>
        <h2>{headline}</h2>
        <p>
          {result.final_status}
          {result.product_uid ? ` · ${result.product_uid}` : ""}
        </p>
      </div>

      <div className="grid-2">
        <article className="card">
          <h3>record_integrity</h3>
          <p>
            {integrity.status || "UNVERIFIABLE"}
            {integrity.failing_layer ? ` · layer ${integrity.failing_layer}` : ""}
          </p>
          {(integrity.reasons || []).map((reason) => (
            <p key={reason} className="muted">
              {reason}
            </p>
          ))}
        </article>
        <article className="card">
          <h3>physical_checks</h3>
          <ul className="flags">
            {["box_id", "seal_id", "seal_condition", "laptop_serial"].map((key) => {
              const shown = physicalLine(physical, key);
              const unchecked = (physical[key] || "NOT_CHECKED") === "NOT_CHECKED";
              return (
                <li key={key}>
                  <span>{key}</span>
                  <strong className={unchecked ? "not-checked" : ""}>{shown}</strong>
                </li>
              );
            })}
          </ul>
        </article>
      </div>

      <article className="card">
        <h3>restriction_flags</h3>
        <FlagList flags={result.restriction_flags} />
        {result.restriction_flags?.location_mismatch ? (
          <p className="error">Verifier GPS is more than 50 km from the current warehouse — flagged suspicious.</p>
        ) : null}
      </article>

      {result.mail_alert?.queued ? (
        <article className="card">
          <h3>Mail alert</h3>
          <p>Queued to {(result.mail_alert.to || []).join(", ") || "registered parties"}.</p>
          {result.mail_alert.channel === "outbox" ? (
            <p className="muted">
              {result.mail_alert.detail
                ? `Gmail did not accept the message. A copy is in mail_outbox/${result.mail_alert.outbox || ""}. ${result.mail_alert.detail}`
                : `SMTP is not configured, so this was not delivered. Open mail_outbox/${result.mail_alert.outbox || ""}.`}
            </p>
          ) : (
            <p className="muted">Sent over SMTP to the registered mail ids.</p>
          )}
        </article>
      ) : result.final_status === "SUSPICIOUS" ? (
        <article className="card">
          <h3>Mail alert</h3>
          <p className="error">
            {result.mail_alert?.detail ||
              "Suspicious, but no registered email was found for the manufacturer or custodian."}
          </p>
          {(result.mail_alert?.to || []).length ? (
            <p className="muted">Intended recipients: {result.mail_alert.to.join(", ")}</p>
          ) : null}
        </article>
      ) : null}

      <AssessmentCard assessment={result.assessment} />

      <article className="card">
        <h3>GPS</h3>
        <GpsMap points={points} />
      </article>

      {result.brand || result.model_name || result.serial_number_masked ? (
        <article className="card">
          <h3>Product</h3>
          <p>
            {[result.brand, result.model_name].filter(Boolean).join(" · ") || "Unknown model"}
          </p>
          <p className="mono">{full ? result.serial_number : result.serial_number_masked}</p>
        </article>
      ) : null}

      {(result.events || []).length ? (
        <article className="card">
          <h3>Provenance</h3>
          <p className="muted">Each handover is a new event with its own hash. Verified means each previous_hash equals the prior event_hash.</p>
          <table className="plain">
            <thead>
              <tr>
                <th>Seq</th>
                <th>Event</th>
                <th>GPS</th>
                {full ? <th>Previous hash</th> : null}
                {full ? <th>Event hash</th> : null}
                {full ? <th>Chain</th> : null}
              </tr>
            </thead>
            <tbody>
              {result.events.map((event, index) => {
                const prior = result.events[index - 1];
                const previous = (event.previous_hash || "").toLowerCase();
                const priorHash = (prior?.event_hash || "").toLowerCase();
                const genesis = "0".repeat(64);
                let chain = "—";
                if (!full) chain = null;
                else if (index === 0) chain = previous.replace(/^0x/, "") === genesis || !previous ? "genesis" : "break";
                else chain = previous && priorHash && previous.replace(/^0x/, "") === priorHash.replace(/^0x/, "") ? "linked" : "break";
                return (
                  <tr key={`${event.seq}-${event.event_uid || event.event_type}`}>
                    <td>{event.seq}</td>
                    <td>{event.event_type}</td>
                    <td>{event.gps_status || event.gps?.gps_status || "NOT_REQUESTED"}</td>
                    {full ? <td className="mono">{event.previous_hash || "—"}</td> : null}
                    {full ? <td className="mono">{event.event_hash || "—"}</td> : null}
                    {full ? <td className={chain === "break" ? "error" : "status-valid"}>{chain}</td> : null}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </article>
      ) : null}
    </section>
  );
}
