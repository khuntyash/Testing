import { Navigate, useParams } from "react-router-dom";
import { getPlatformById } from "../constants/platforms.js";
import WorkspaceView from "../components/WorkspaceView.jsx";

export default function WorkspacePage() {
  const { platformId } = useParams();
  const platform = getPlatformById(platformId ?? "");

  if (!platform) {
    return <Navigate to="/" replace />;
  }

  return <WorkspaceView platform={platform} />;
}
