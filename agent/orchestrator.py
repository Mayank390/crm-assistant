"""
Async orchestration utilities for chaining multiple tool calls with
parallelization, retries, timeouts, caching, and tracing.

This module is intentionally lightweight and dependency-free beyond
the standard library and OpenTelemetry to make it easy to adopt.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from time import perf_counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple, Union

import os
logger = logging.getLogger(__name__)


Jsonable = Union[str, int, float, bool, None, Dict[str, Any], List[Any]]


def _hash_inputs(value: Any) -> str:
    try:
        serialized = json.dumps(value, sort_keys=True, default=str)
    except Exception:
        serialized = str(value)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


@dataclass
class StepSpec:
    """Specification for a single orchestration step.

    - name: unique name for the step
    - coroutine: async callable executed for this step
    - requires: names of context keys that must exist before this step can run
    - provides: context key under which to store the result (optional)
    - timeout_s: time limit for the step (None means no timeout)
    - retries: number of retries on failure
    - retry_backoff_s: base backoff for exponential backoff with jitter
    - cache_key: optional static cache key; if not provided, derived from inputs
    - validator: optional callable(result, context) -> bool to gate downstream steps
    - parallel_group: identifier to group steps that can run in parallel together
    """

    name: str
    coroutine: Callable[[Dict[str, Any]], Awaitable[Any]]
    requires: Sequence[str] = field(default_factory=tuple)
    provides: Optional[str] = None
    timeout_s: Optional[float] = None
    retries: int = 0
    retry_backoff_s: float = 0.5
    cache_key: Optional[str] = None
    validator: Optional[Callable[[Any, Dict[str, Any]], bool]] = None
    parallel_group: Optional[str] = None


class Orchestrator:
    """Executes a set of StepSpec instances with dependency management.

    Features:
    - Runs independent steps in parallel per tick using parallel_group labels
    - Enforces requires/provides contracts via a shared context dict
    - Retries with exponential backoff and optional timeouts
    - Simple in-memory caching keyed by inputs
    - OpenTelemetry tracing per step
    """

    def __init__(self, tracer_name: str = __name__, max_parallel: int = 5):
        self.tracer = None
        self.max_parallel = max_parallel
        self._cache: Dict[str, Any] = {}

    def _make_cache_key(self, step: StepSpec, context: Dict[str, Any]) -> Optional[str]:
        if step.cache_key:
            return step.cache_key
        if not step.requires:
            return None
        inputs = {k: context.get(k) for k in step.requires}
        return f"{step.name}:{_hash_inputs(inputs)}"

    async def _execute_one(self, step: StepSpec, context: Dict[str, Any], correlation_id: Optional[str]) -> Tuple[str, Any, Optional[Exception]]:
        cache_key = self._make_cache_key(step, context)
        if cache_key and cache_key in self._cache:
            return step.name, self._cache[cache_key], None

        attempt = 0
        last_exc: Optional[Exception] = None
        backoff = step.retry_backoff_s
        while attempt <= step.retries:
            start = time.time()
            try:
                coro = step.coroutine(context)
                result = await (asyncio.wait_for(coro, step.timeout_s) if step.timeout_s else coro)

                # Optional validation gate
                if step.validator is not None:
                    is_valid = False
                    try:
                        is_valid = bool(step.validator(result, context))
                    except Exception:
                        is_valid = False
                    if not is_valid:
                        raise RuntimeError(f"Validation failed for step '{step.name}'")

                if cache_key:
                    self._cache[cache_key] = result
                # duration and preview kept for potential future logging (no-op here)
                _ = int((time.time() - start) * 1000)
                try:
                    _ = str(result)[:400]
                except Exception:
                    _ = "<unserializable>"
                return step.name, result, None
            except Exception as e:  # noqa: BLE001
                last_exc = e
                pass
            # Retry with backoff
            attempt += 1
            if attempt <= step.retries:
                await asyncio.sleep(backoff)
                backoff *= 2

        return step.name, None, last_exc

    async def run(self, steps: Sequence[StepSpec], initial_context: Optional[Dict[str, Any]] = None, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        orchestrator_start_time = perf_counter()
        context: Dict[str, Any] = dict(initial_context or {})

        # Build dependency graph: step -> required keys
        remaining: Dict[str, StepSpec] = {s.name: s for s in steps}

        while remaining:
            # Pick ready steps (all requires present in context)
            ready: List[StepSpec] = [s for s in remaining.values() if all(req in context for req in s.requires)]
            if not ready:
                missing = {s.name: [r for r in s.requires if r not in context] for s in remaining.values()}
                raise RuntimeError(f"Deadlock: no ready steps; missing inputs: {missing}")

            # Group by parallel_group to allow multiple groups per tick
            groups: Dict[str, List[StepSpec]] = {}
            for s in ready:
                key = s.parallel_group or "__default__"
                groups.setdefault(key, []).append(s)

            # Run each group with bounded concurrency
            for group_steps in groups.values():
                # Cap parallelism to avoid resource contention
                sem = asyncio.Semaphore(self.max_parallel)

                async def _runner(spec: StepSpec) -> Tuple[str, Any, Optional[Exception]]:
                    async with sem:
                        return await self._execute_one(spec, context, correlation_id)

                tasks = [asyncio.create_task(_runner(s)) for s in group_steps]
                for task in asyncio.as_completed(tasks):
                    name, result, exc = await task
                    step = remaining.pop(name, None)
                    if exc is not None:
                        # Stop early on failure; propagate error
                        raise exc
                    if step and step.provides:
                        context[step.provides] = result
        elapsed_ms = (perf_counter() - orchestrator_start_time) * 1000
        print(f"Orchestrator.run completed {len(steps)} steps in {elapsed_ms:.2f} ms")
        return context


# Convenience helpers to wrap simple functions into StepSpec-compatible coroutines
def as_async(fn: Callable[..., Any]) -> Callable[[Dict[str, Any]], Awaitable[Any]]:
    async def _wrapper(ctx: Dict[str, Any]) -> Any:
        return await fn(ctx) if asyncio.iscoroutinefunction(fn) else fn(ctx)
    return _wrapper

