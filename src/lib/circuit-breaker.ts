const FAILURE_THRESHOLD = 5;
const OPEN_TIMEOUT = 30000; // 30 seconds

interface CircuitState {
  failures: number;
  lastFailureTime: number;
  state: "CLOSED" | "OPEN" | "HALF_OPEN";
}

const circuits = new Map<string, CircuitState>();

function getCircuit(key: string): CircuitState {
  let c = circuits.get(key);
  if (!c) {
    c = { failures: 0, lastFailureTime: 0, state: "CLOSED" };
    circuits.set(key, c);
  }
  return c;
}

export async function withCircuitBreaker<T>(
  key: string,
  fn: () => Promise<T>,
): Promise<T> {
  const c = getCircuit(key);

  // transition OPEN -> HALF_OPEN after timeout
  if (c.state === "OPEN" && Date.now() - c.lastFailureTime > OPEN_TIMEOUT) {
    c.state = "HALF_OPEN";
  }

  // in OPEN state, immediately reject
  if (c.state === "OPEN") {
    throw new CircuitOpenError("Circuit breaker is open");
  }

  try {
    const result = await fn();
    // success: reset
    c.failures = 0;
    c.state = "CLOSED";
    return result;
  } catch (error) {
    c.failures++;
    c.lastFailureTime = Date.now();
    if (c.failures >= FAILURE_THRESHOLD) {
      c.state = "OPEN";
    }
    throw error;
  }
}

export class CircuitOpenError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CircuitOpenError";
  }
}
