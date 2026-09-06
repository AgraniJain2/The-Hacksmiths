// One place mapping the engine's status/seat-status strings (see
// app/scheduling/models.py's RequestStatus/InterviewStatus/SeatStatus) to a
// label + pill class. Add a new status here, not as an inline ternary in a
// page — see FRONTEND_DESIGN_SYSTEM.md's utility-class section for the pill
// classes themselves.

const REQUEST_STATUS = {
  collecting_availability: { label: "Collecting availability", pill: "pill-neutral" },
  awaiting_candidate_selection: { label: "Awaiting candidate", pill: "pill-neutral" },
  assigning_panel: { label: "Assigning panel", pill: "pill-warning" },
  panel_complete: { label: "Booked", pill: "pill-success" },
  manual_scheduling_required: { label: "Needs manual scheduling", pill: "pill-danger" },
  cancelled: { label: "Cancelled", pill: "pill-neutral" },
};

const SEAT_STATUS = {
  pending: { label: "Pending", pill: "pill-neutral" },
  offered: { label: "Offer sent", pill: "pill-warning" },
  accepted: { label: "Accepted", pill: "pill-success" },
  exhausted: { label: "Exhausted", pill: "pill-danger" },
};

export function requestStatusMeta(status) {
  return REQUEST_STATUS[status] || { label: status, pill: "pill-neutral" };
}

export function seatStatusMeta(status) {
  return SEAT_STATUS[status] || { label: status, pill: "pill-neutral" };
}
