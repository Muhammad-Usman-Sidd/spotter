import { useCallback, useEffect, useRef, useState } from 'react';
import { requestTripPlan } from '../lib/api';
import type { TripPlan, TripRequest } from '../types/routing';

interface TripPlanState {
  plan: TripPlan | null;
  loading: boolean;
  error: string | null;
}

export function useTripPlan() {
  const [state, setState] = useState<TripPlanState>({ plan: null, loading: false, error: null });
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const submit = useCallback(async (request: TripRequest) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState((previous) => ({ ...previous, loading: true, error: null }));
    try {
      const plan = await requestTripPlan(request, controller.signal);
      setState({ plan, loading: false, error: null });
    } catch (error) {
      if (controller.signal.aborted) return;
      const message = error instanceof Error ? error.message : 'Unexpected error';
      setState((previous) => ({ ...previous, loading: false, error: message }));
    }
  }, []);

  return { ...state, submit };
}
