const RETRYABLE_STATUSES = new Set([502, 503, 504]);

export async function fetchWithRetry(
  url: string,
  options?: RequestInit,
  maxRetries = 3,
  baseDelay = 1000,
): Promise<Response> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      const response = await fetch(url, options);
      if (!response.ok && RETRYABLE_STATUSES.has(response.status)) {
        if (attempt < maxRetries) {
          const delay = baseDelay * Math.pow(2, attempt);
          await sleep(delay);
          continue;
        }
      }
      return response;
    } catch (error) {
      lastError = error;
      if (attempt < maxRetries) {
        const delay = baseDelay * Math.pow(2, attempt);
        await sleep(delay);
      }
    }
  }
  throw lastError;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
