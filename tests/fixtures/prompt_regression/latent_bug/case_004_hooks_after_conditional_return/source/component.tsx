import { useState } from "react";
import { Navigate } from "react-router-dom";

export function OnboardingPage({ loading, hasOrgs }: { loading: boolean; hasOrgs: boolean }) {
  if (loading) return <div>Loading...</div>;
  if (hasOrgs) return <Navigate to="/home" replace />;

  const [name, setName] = useState("");      // useState AFTER conditional returns
  const [slug, setSlug] = useState("");      // useState AFTER conditional returns
  return <div>{name}{slug}</div>;
}
