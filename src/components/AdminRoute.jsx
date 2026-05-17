import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";

/**
 * Requires authenticated admin session.
 */
export default function AdminRoute() {
  const { authReady, isAuthenticated, user } = useAuth();

  if (!authReady) return null;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  if (!user?.isAdmin) return <Navigate to="/" replace />;
  return <Outlet />;
}
