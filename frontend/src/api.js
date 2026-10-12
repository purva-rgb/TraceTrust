function formatDetail(detail) {
  if (detail == null) return "Request failed";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  if (typeof detail === "object") {
    const parts = [detail.code, detail.message].filter(Boolean);
    const extras = [];
    if (detail.missing?.length) extras.push(`missing ${detail.missing.join(", ")}`);
    if (detail.unexpected?.length) extras.push(`unexpected ${detail.unexpected.join(", ")}`);
    if (detail.mismatched?.length) {
      extras.push(
        `mismatched ${detail.mismatched.map((item) => item.product_uid || JSON.stringify(item)).join(", ")}`,
      );
    }
    if (detail.location_check) extras.push(`location_check ${detail.location_check}`);
    return [...parts, ...extras].join(" — ") || JSON.stringify(detail);
  }
  return String(detail);
}

export function formatError(data) {
  if (!data) return "Request failed";
  if (data.detail !== undefined) return formatDetail(data.detail);
  return data.message || "Request failed";
}

export async function api(path, { method = "GET", token, body, idempotencyKey } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!response.ok) {
    const error = new Error(formatError(data));
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

export function newIdempotencyKey() {
  return crypto.randomUUID();
}

export async function pollOperation(token, operationUid, { intervalMs = 1000, maxTries = 40 } = {}) {
  let last = null;
  for (let attempt = 0; attempt < maxTries; attempt += 1) {
    last = await api(`/operations/${operationUid}`, { token });
    if (["CONFIRMED", "FAILED", "RECONCILIATION_REQUIRED"].includes(last.status)) {
      return last;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return last;
}
