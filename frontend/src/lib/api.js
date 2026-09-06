// The only module allowed to call the backend directly (mirrors the
// backend's own "all config through config.py" rule — one seam, not fetch()
// scattered through components). Every request sends cookies, since the
// session lives in an httpOnly cookie the backend sets — see AUTH_MODULE.md.

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

class ApiError extends Error {
  constructor(status, detail, reason) {
    super(detail || `request_failed_${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.reason = reason;
  }
}

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });

  let body = null;
  try {
    body = await res.json();
  } catch {
    // No/invalid JSON body — fine for e.g. a plain 204 or a redirect chain.
  }

  if (!res.ok) {
    throw new ApiError(res.status, body?.detail, body?.reason);
  }
  return body;
}

export const api = {
  /** Current user + Google connection state. 401 (ApiError) means "not logged in". */
  me: () => request("/auth/me"),

  logout: () => request("/auth/logout", { method: "POST" }),

  disconnectGoogle: () => request("/auth/google/disconnect", { method: "POST" }),

  /**
   * Not a fetch target — this is a real browser navigation into the OAuth
   * dance, so callers should assign it to `window.location.href` or an
   * <a href>, never call it through `request()`.
   */
  googleLoginUrl: (inviteToken) =>
    `${API_BASE_URL}/auth/google/login${
      inviteToken ? `?invite_token=${encodeURIComponent(inviteToken)}` : ""
    }`,
};

export { ApiError };
