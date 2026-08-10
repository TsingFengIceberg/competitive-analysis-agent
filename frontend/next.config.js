/**
 * CI-Agent Frontend — Next.js Configuration
 */
function getInternalServiceURL(envKey, fallbackURL) {
  const configured = process.env[envKey]?.trim();
  return configured && configured.length > 0
    ? configured.replace(/\/+$/, "")
    : fallbackURL;
}

/** @type {import("next").NextConfig} */
const config = {
  allowedDevOrigins: ["121.43.235.19"],
  devIndicators: false,
  async rewrites() {
    const rewrites = [];
    const gatewayURL = getInternalServiceURL(
      "CA_AGENT_API_BASE_URL",
      "http://127.0.0.1:8001",
    );

    if (!process.env.NEXT_PUBLIC_BACKEND_BASE_URL) {
      rewrites.push({
        source: "/api/:path*",
        destination: `${gatewayURL}/api/:path*`,
      });
    }

    return rewrites;
  },
};

export default config;
