import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
  experimental: {
    // Next's rewrite proxy aborts proxied API calls after 30 s by default,
    // which silently killed slow endpoints: the AI assistant (30-60 s on the
    // CPU-only VPS), report generation and large imports all came back as
    // "Internal Server Error" before the backend had even finished.
    proxyTimeout: 600_000,
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        // Local dev default: port 8001 (8000 is occupied by another service
        // on the dev machine). Docker/compose sets API_URL=http://backend:8000.
        destination: `${process.env.API_URL ?? 'http://localhost:8001'}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
