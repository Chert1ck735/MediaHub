import { useEffect, type ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

type ProtectedRouteProps = {
  authToken: string;
  onRequireAuth?: () => void;
  children?: ReactNode;
};

export function ProtectedRoute({ authToken, onRequireAuth, children }: ProtectedRouteProps) {
  const location = useLocation();

  useEffect(() => {
    if (!authToken) {
      onRequireAuth?.();
    }
  }, [authToken, onRequireAuth]);

  if (authToken) {
    return children ? <>{children}</> : <Outlet />;
  }

  const redirect = encodeURIComponent(`${location.pathname}${location.search}`);
  return <Navigate to={`/?auth=login&redirect=${redirect}`} replace />;
}
