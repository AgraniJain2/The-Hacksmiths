import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ThemeProvider } from "./context/ThemeContext";
import { AuthProvider } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import AppShell from "./components/AppShell";
import Login from "./pages/Login";
import AuthComplete from "./pages/AuthComplete";
import Dashboard from "./pages/Dashboard";
import GoogleConnection from "./pages/GoogleConnection";
import RequestNew from "./pages/RequestNew";
import RequestList from "./pages/RequestList";
import RequestDetail from "./pages/RequestDetail";
import InterviewerProfile from "./pages/InterviewerProfile";
import InterviewerOffers from "./pages/InterviewerOffers";
import Candidate from "./pages/Candidate";
import Notifications from "./pages/Notifications";
import NotFound from "./pages/NotFound";

// Route map. Adding a new authenticated page? Nest it under the AppShell
// layout route below rather than adding a top-level route — see
// Documentation/FRONTEND_DESIGN_SYSTEM.md "Adding a new page".
export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/auth/complete" element={<AuthComplete />} />

            <Route element={<ProtectedRoute />}>
              <Route element={<AppShell />}>
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/settings/google" element={<GoogleConnection />} />
                <Route path="/notifications" element={<Notifications />} />

                <Route path="/requests/new" element={<RequestNew />} />
                <Route path="/requests" element={<RequestList />} />
                <Route path="/requests/:requestId" element={<RequestDetail />} />

                <Route path="/interviewer/profile" element={<InterviewerProfile />} />
                <Route path="/interviewer/offers" element={<InterviewerOffers />} />

                <Route path="/candidate" element={<Candidate />} />
              </Route>
            </Route>

            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
