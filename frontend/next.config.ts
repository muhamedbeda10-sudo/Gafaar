import type { NextConfig } from "next";

// Static export: the UI is plain files (Firebase Hosting friendly) that talk to the API.
const nextConfig: NextConfig = { output: "export", trailingSlash: true, images: { unoptimized: true } };
export default nextConfig;
