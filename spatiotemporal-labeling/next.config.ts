import type { NextConfig } from "next";

// In production, set NEXT_PUBLIC_API_URL=/backend and BACKEND_URL=<FastAPI URL>.
// The browser then calls /backend/* on this same origin and Next proxies it to the
// API, so the auth cookies stay first-party (SameSite=Lax works, no third-party cookies).
const BACKEND_URL = process.env.BACKEND_URL?.replace(/\/+$/, "");

const nextConfig: NextConfig = {
  async rewrites() {
    if (!BACKEND_URL) return [];
    return [
      {
        source: "/backend/:path*",
        destination: `${BACKEND_URL}/:path*`,
      },
    ];
  },
};

export default nextConfig;
