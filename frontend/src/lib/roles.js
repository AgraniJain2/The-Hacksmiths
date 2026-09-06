// Where each role lands after auth, and small role-group helpers used by
// nav/route decisions across pages — one place so "who can see what" stays
// consistent with the backend's own RBAC checks (see CONVENTIONS.md).

export const STAFF_ROLES = ["recruiter", "hiring_manager"];

export function homeRouteFor(role) {
  return role === "candidate" ? "/candidate" : "/dashboard";
}

export function isStaff(role) {
  return STAFF_ROLES.includes(role);
}
