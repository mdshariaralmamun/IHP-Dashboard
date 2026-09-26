import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  output: 'standalone',
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
