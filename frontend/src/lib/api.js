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

  // ---- Scheduling (app/scheduling/router.py) ----------------------------
  // Backed by an in-memory store (state resets if the backend restarts) and
  // mock Calendar/notification providers — see Documentation/SCHEDULER.md
  // and the store's own docstring. Real DB + Calendar wiring is follow-up
  // work, not yet built; this is the honest "current implementation."

  /** Recruiter/hiring_manager: create a request. Returns {request, round, invite_link}. */
  createRequest: (body) => request("/scheduling/requests", { method: "POST", body: JSON.stringify(body) }),

  /** Recruiter/hiring_manager: every request they can see. */
  listRequests: () => request("/scheduling/requests"),

  /** Any role permitted to view this specific request (staff, or its own candidate). */
  getRequest: (requestId) => request(`/scheduling/requests/${requestId}`),

  /** Candidate: their own request, or null if none exists yet. */
  myRequest: () => request("/scheduling/my-request"),

  /** Candidate: submit availability windows ({start, end, source_timezone}[], UTC ISO strings). */
  submitAvailability: (requestId, windows) =>
    request(`/scheduling/requests/${requestId}/availability`, {
      method: "POST",
      body: JSON.stringify({ windows }),
    }),

  /** Candidate: pick one feasible slot by id. */
  selectSlot: (requestId, slotId) =>
    request(`/scheduling/requests/${requestId}/select-slot`, {
      method: "POST",
      body: JSON.stringify({ slot_id: slotId }),
    }),

  /** Candidate: cancel their interview. */
  cancelRequest: (requestId) => request(`/scheduling/requests/${requestId}/cancel`, { method: "POST" }),

  /** Candidate: cancel + immediately resubmit new availability windows. */
  rescheduleRequest: (requestId, windows) =>
    request(`/scheduling/requests/${requestId}/reschedule`, {
      method: "POST",
      body: JSON.stringify({ windows }),
    }),

  /** Interviewer: their own pool profile, or null if never registered. */
  getMyInterviewerProfile: () => request("/scheduling/interviewer/profile"),

  /** Interviewer: create/update their pool profile. */
  saveMyInterviewerProfile: (body) =>
    request("/scheduling/interviewer/profile", { method: "PUT", body: JSON.stringify(body) }),

  /** Interviewer: seats currently offered or accepted to them. */
  myOffers: () => request("/scheduling/interviewer/offers"),

  /** Interviewer: accept or decline one seat offer. */
  respondToSeat: (interviewId, seatIndex, accept) =>
    request(`/scheduling/interviews/${interviewId}/seats/${seatIndex}/respond`, {
      method: "POST",
      body: JSON.stringify({ accept }),
    }),

  /** Interviewer: back out of a seat already accepted. */
  interviewerCancelSeat: (interviewId) =>
    request(`/scheduling/interviews/${interviewId}/interviewer-cancel`, { method: "POST" }),

  /** Recruiter/hiring_manager: the interviewer directory. */
  listInterviewers: () => request("/scheduling/interviewers"),

  /** Anyone: their own notification inbox (offers, confirmations, escalations, ...). */
  myNotifications: () => request("/scheduling/notifications"),
};

export { ApiError };
