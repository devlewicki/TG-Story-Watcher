"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export function useFetch<T>(fetcher: (signal: AbortSignal) => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const ctrl = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    ctrl.current?.abort();
    const controller = new AbortController();
    ctrl.current = controller;
    setLoading(true);
    setError(null);
    try {
      const res = await fetcher(controller.signal);
      if (!controller.signal.aborted) {
        setData(res);
        setLoading(false);
      }
    } catch (e) {
      if (!controller.signal.aborted) {
        setError((e as Error).message);
        setLoading(false);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    run();
    return () => ctrl.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error, refresh: run };
}