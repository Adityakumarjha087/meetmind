"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ErrorState, LoadingState } from "@/components/states";
import { useAuth } from "@/lib/auth-context";

export default function OAuthCallback() {
  const { acceptToken } = useAuth();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const token = params.get("access_token");
    window.history.replaceState(null, "", window.location.pathname);
    if (!token) {
      setError(params.get("error") ?? "Sign-in failed");
      return;
    }
    acceptToken(token)
      .then(() => router.replace("/meetings"))
      .catch(() => setError("Could not complete sign-in"));
  }, [acceptToken, router]);

  return (
    <div className="mx-auto max-w-md p-8">
      {error ? <ErrorState message={error} onRetry={() => router.replace("/login")} /> : <LoadingState label="Signing you in…" />}
    </div>
  );
}
