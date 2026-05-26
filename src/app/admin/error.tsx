"use client";

import { useEffect } from "react";
import { logger } from "@/lib/logger";

export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    logger.error("Admin error:", error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950">
      <div className="text-center p-8">
        <h1 className="text-2xl font-bold text-white mb-4">
          Admin panel error
        </h1>
        <p className="text-white/60 mb-6 max-w-md">
          The admin panel encountered an unexpected error. Please try refreshing.
        </p>
        <button
          onClick={reset}
          className="px-6 py-2.5 bg-white text-black rounded-lg font-medium hover:bg-white/90 transition-colors"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
