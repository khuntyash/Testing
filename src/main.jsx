import { Suspense, StrictMode, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext.jsx";
import { WalletProvider } from "./wallet/WalletContext.jsx";
import AppLayout from "./AppLayout.jsx";
import AdminRoute from "./components/AdminRoute.jsx";
import AppErrorBoundary from "./components/AppErrorBoundary.jsx";
import ProtectedRoute from "./components/ProtectedRoute.jsx";
import ScrollToTop from "./components/ScrollToTop.jsx";

const HomePage = lazy(() => import("./pages/HomePage.jsx"));
const LoginPage = lazy(() => import("./pages/LoginPage.jsx"));
const BlogPage = lazy(() => import("./pages/BlogPage.jsx"));
const AboutUsPage = lazy(() => import("../AboutUs.jsx"));
const HistoryPage = lazy(() => import("./pages/HistoryPage.jsx"));
const UserHistoryPage = lazy(() => import("./pages/UserHistoryPage.jsx"));
const MyDashboardPage = lazy(() => import("./pages/MyDashboardPage.jsx"));
const AdminPage = lazy(() => import("./pages/AdminPage.jsx"));
const ProfilePage = lazy(() => import("./pages/ProfilePage.jsx"));
const SignupPage = lazy(() => import("./pages/SignupPage.jsx"));
const WalletPage = lazy(() => import("./pages/WalletPage.jsx"));
const WorkspacePage = lazy(() => import("./pages/WorkspacePage.jsx"));

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <WalletProvider>
          <ScrollToTop />
          <AppErrorBoundary>
            <Suspense fallback={<div style={{ padding: 20 }}>Loading...</div>}>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/signup" element={<SignupPage />} />
                <Route element={<ProtectedRoute />}>
                  <Route element={<AppLayout />}>
                    <Route path="/" element={<HomePage />} />
                    <Route path="/about" element={<AboutUsPage />} />
                    <Route path="/blog" element={<BlogPage />} />
                    <Route path="/history" element={<HistoryPage />} />
                    <Route path="/user-history" element={<UserHistoryPage />} />
                    <Route path="/my-dashboard" element={<MyDashboardPage />} />
                    <Route path="/wallet" element={<WalletPage />} />
                    <Route path="/profile" element={<ProfilePage />} />
                    <Route path="/:platformId" element={<WorkspacePage />} />
                    <Route element={<AdminRoute />}>
                      <Route path="/admin" element={<AdminPage />} />
                    </Route>
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Route>
                </Route>
              </Routes>
            </Suspense>
          </AppErrorBoundary>
        </WalletProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
