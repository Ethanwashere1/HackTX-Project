import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { RequireAuth } from "./auth/RequireAuth";
import { AppShell } from "./components/AppShell";
import "./components/ui.css";
import { CreateEventPage } from "./pages/CreateEvent";
import { CreateOrgPage } from "./pages/CreateOrg";
import { EventDetailsPage } from "./pages/EventDetails";
import { GroupPageView } from "./pages/Group";
import { InterviewPage } from "./pages/Interview";
import { JoinEventPage } from "./pages/JoinEvent";
import { LoginPage } from "./pages/Login";
import { OrgFeedPage } from "./pages/OrgFeed";
import { ProfilePage } from "./pages/Profile";
import { RecommendationsPage } from "./pages/Recommendations";
import { RequestsPage } from "./pages/Requests";
import { ThreadPage } from "./pages/Thread";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route path="/" element={<Navigate to="/orgs/org_ut" replace />} />
            <Route path="/orgs/new" element={<CreateOrgPage />} />
            <Route path="/orgs/:id" element={<OrgFeedPage />} />
            <Route path="/events/new" element={<CreateEventPage />} />
            <Route path="/events/:eventId" element={<EventDetailsPage />} />
            <Route path="/events/:eventId/join" element={<JoinEventPage />} />
            <Route path="/events/:eventId/interview" element={<InterviewPage />} />
            <Route
              path="/events/:eventId/recommendations"
              element={<RecommendationsPage />}
            />
            <Route path="/requests" element={<RequestsPage />} />
            <Route path="/threads/:threadId" element={<ThreadPage />} />
            <Route path="/groups/:groupId" element={<GroupPageView />} />
            <Route path="/profile" element={<ProfilePage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
