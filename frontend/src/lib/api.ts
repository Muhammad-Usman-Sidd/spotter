import type { TripPlan, TripRequest } from '../types/routing';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isTripPlan(value: unknown): value is TripPlan {
  return (
    isRecord(value) &&
    Array.isArray(value.routes) &&
    isRecord(value.heatmap) &&
    Array.isArray(value.heatmap.points) &&
    isRecord(value.meta)
  );
}

function describeError(payload: unknown, status: number): string {
  if (isRecord(payload)) {
    if (typeof payload.detail === 'string') return payload.detail;
    const lines = Object.entries(payload).map(([field, messages]) => {
      const text = Array.isArray(messages) ? messages.join(' ') : String(messages);
      return field === 'non_field_errors' ? text : `${field}: ${text}`;
    });
    if (lines.length > 0) return lines.join(' | ');
  }
  return `Request failed with status ${status}`;
}

export async function requestTripPlan(request: TripRequest, signal: AbortSignal): Promise<TripPlan> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/api/plan/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('The routing service is unreachable. Confirm the backend is running.', 0);
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(describeError(payload, response.status), response.status);
  if (!isTripPlan(payload)) throw new ApiError('The routing service returned an unexpected response.', response.status);
  return payload;
}
