export async function copyText(text) {
  if (!text) return;
  await navigator.clipboard.writeText(text);
}
