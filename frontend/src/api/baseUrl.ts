const API_PORT = import.meta.env.VITE_API_PORT ?? "8080";

export function getApiBase(): string {
  return (
    import.meta.env.VITE_API_BASE_URL ??
    `${window.location.protocol}//${window.location.hostname}:${API_PORT}`
  );
}
