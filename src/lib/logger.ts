const IS_PRODUCTION = typeof process !== "undefined" && process.env?.NODE_ENV === "production";

export const logger = {
  error: (...args: unknown[]) => {
    if (!IS_PRODUCTION) {
      console.error(...args);
    }
  },
  warn: (...args: unknown[]) => {
    if (!IS_PRODUCTION) {
      console.warn(...args);
    }
  },
  log: (...args: unknown[]) => {
    if (!IS_PRODUCTION) {
      console.log(...args);
    }
  },
};
