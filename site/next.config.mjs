/** @type {import('next').NextConfig} */
const isDev = process.env.NODE_ENV === "development";

// Where the live demo's engine lives.
//  - Production/preview (Vercel): the Python function in api/demo.py. Every
//    /api/demo/* path is folded onto it; the function reads the original path.
//  - `next dev`: a locally running `autocorrect-sandbox --no-browser`
//    (override with AUTOCORRECT_ENGINE_URL), since `next dev` does not run
//    Vercel Python functions.
const devEngine = (process.env.AUTOCORRECT_ENGINE_URL ?? "http://127.0.0.1:8765").replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return isDev
      ? [{ source: "/api/demo/:path*", destination: `${devEngine}/api/:path*` }]
      : [{ source: "/api/demo/:path*", destination: "/api/demo" }];
  },
};

export default nextConfig;
