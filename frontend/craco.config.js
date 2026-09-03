// craco.config.js
const path = require("path");
require("dotenv").config();

const LUCIDE_REACT_PATTERN = /[\\/]node_modules[\\/]lucide-react[\\/]/;

function excludeLucideFromSourceMapLoader(rules = []) {
  for (const rule of rules) {
    if (Array.isArray(rule.oneOf)) {
      excludeLucideFromSourceMapLoader(rule.oneOf);
    }

    if (Array.isArray(rule.rules)) {
      excludeLucideFromSourceMapLoader(rule.rules);
    }

    const uses = Array.isArray(rule.use) ? rule.use : rule.use ? [rule.use] : [];
    const hasSourceMapLoader =
      typeof rule.loader === "string" && rule.loader.includes("source-map-loader")
      || uses.some((entry) => {
        if (typeof entry === "string") return entry.includes("source-map-loader");
        return typeof entry?.loader === "string" && entry.loader.includes("source-map-loader");
      });

    if (!hasSourceMapLoader) continue;

    if (!rule.exclude) {
      rule.exclude = [LUCIDE_REACT_PATTERN];
      continue;
    }

    if (Array.isArray(rule.exclude)) {
      rule.exclude.push(LUCIDE_REACT_PATTERN);
      continue;
    }

    rule.exclude = [rule.exclude, LUCIDE_REACT_PATTERN];
  }
}

// Check if we're in development/preview mode (not production build)
// Craco sets NODE_ENV=development for start, NODE_ENV=production for build
const isDevServer = process.env.NODE_ENV !== "production";

// Environment variable overrides
const config = {
  enableHealthCheck: process.env.ENABLE_HEALTH_CHECK === "true",
};

// Conditionally load health check modules only if enabled
let WebpackHealthPlugin;
let setupHealthEndpoints;
let healthPluginInstance;

if (config.enableHealthCheck) {
  WebpackHealthPlugin = require("./plugins/health-check/webpack-health-plugin");
  setupHealthEndpoints = require("./plugins/health-check/health-endpoints");
  healthPluginInstance = new WebpackHealthPlugin();
}

let webpackConfig = {
  eslint: {
    configure: {
      extends: ["plugin:react-hooks/recommended"],
      rules: {
        "react-hooks/rules-of-hooks": "error",
        "react-hooks/exhaustive-deps": "warn",
      },
    },
  },
  webpack: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
    configure: (webpackConfig) => {
      excludeLucideFromSourceMapLoader(webpackConfig.module?.rules || []);
      webpackConfig.ignoreWarnings = [
        ...(webpackConfig.ignoreWarnings || []),
        /Failed to parse source map/,
      ];

      // Add ignored patterns to reduce watched directories
        webpackConfig.watchOptions = {
          ...webpackConfig.watchOptions,
          ignored: [
            '**/node_modules/**',
            '**/.git/**',
            '**/build/**',
            '**/dist/**',
            '**/coverage/**',
            '**/public/**',
        ],
      };

      // Add health check plugin to webpack if enabled
      if (config.enableHealthCheck && healthPluginInstance) {
        webpackConfig.plugins.push(healthPluginInstance);
      }
      return webpackConfig;
    },
  },
};

webpackConfig.devServer = (devServerConfig) => {
  devServerConfig.historyApiFallback = {
    ...(devServerConfig.historyApiFallback || {}),
    disableDotRule: true,
    index: "/index.html",
  };

  // Add health check endpoints if enabled
  if (config.enableHealthCheck && setupHealthEndpoints && healthPluginInstance) {
    const originalSetupMiddlewares = devServerConfig.setupMiddlewares;

    devServerConfig.setupMiddlewares = (middlewares, devServer) => {
      // Call original setup if exists
      if (originalSetupMiddlewares) {
        middlewares = originalSetupMiddlewares(middlewares, devServer);
      }

      // Setup health endpoints
      setupHealthEndpoints(devServer, healthPluginInstance);

      return middlewares;
    };
  }

  return devServerConfig;
};

// Wrap with visual edits (automatically adds babel plugin, dev server, and overlay in dev mode)
if (isDevServer) {
  try {
    const { withVisualEdits } = require("@emergentbase/visual-edits/craco");
    webpackConfig = withVisualEdits(webpackConfig);
  } catch (err) {
    if (err.code === 'MODULE_NOT_FOUND' && err.message.includes('@emergentbase/visual-edits/craco')) {
      console.warn(
        "[visual-edits] @emergentbase/visual-edits not installed — visual editing disabled."
      );
    } else {
      throw err;
    }
  }
}

module.exports = webpackConfig;
