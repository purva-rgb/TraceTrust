export function supportPoints(score) {
  return Math.round(Number(score || 0) * 100);
}

export const CAUSE_COPY = {
  CLONED_QR: "Copied QR code",
  DEVICE_OR_PACKAGE_SUBSTITUTION: "Box or seal swap",
  DIVERSION_OR_GRAY_MARKET: "Wrong place in the supply chain",
  RECORD_TAMPERING: "Digital record was altered",
  PROCESS_RECORDING_GAP: "Process / recording gap",
};

export function leadingScore(assessment) {
  if (!assessment) return { points: 0, cause: null, label: null };
  const hypotheses = (assessment.hypotheses || []).filter(
    (item) => item.cause !== "PROCESS_RECORDING_GAP" && Number(item.support_score) > 0,
  );
  const top = hypotheses[0] || assessment.leading;
  if (top && Number(top.support_score) > 0) {
    return {
      points: top.support_points ?? supportPoints(top.support_score),
      cause: top.cause,
      label: top.label || CAUSE_COPY[top.cause] || top.cause,
    };
  }
  const byCause = assessment.by_cause || {};
  let bestCause = null;
  let best = 0;
  for (const [cause, score] of Object.entries(byCause)) {
    if (cause === "PROCESS_RECORDING_GAP") continue;
    const value = Number(score) || 0;
    if (value > best) {
      best = value;
      bestCause = cause;
    }
  }
  return {
    points: supportPoints(best),
    cause: bestCause,
    label: bestCause ? CAUSE_COPY[bestCause] || bestCause : null,
  };
}
