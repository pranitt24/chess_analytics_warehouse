const MOCK = import.meta.env.VITE_USE_MOCK === '1';
export async function getJSON(path) {
  const url = MOCK ? `/mock/${path.split('?')[0].replace(/^\/api\//, '').replaceAll('/', '_')}.json` : path;
  const r = await fetch(url);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  return r.json();
}
