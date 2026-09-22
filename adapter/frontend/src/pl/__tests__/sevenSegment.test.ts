import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createDefaultPinResolver } from '../../simulation/PinResolver';
import { PartSimulationRegistry } from '../../simulation/parts/PartSimulationRegistry';
import '../../simulation/parts/ChipParts';

vi.mock('../../store/useSimulatorStore', () => ({
  useSimulatorStore: { getState: () => ({ wires: [] }) },
}));

function attach(pins: Record<string, number>, digits = 1) {
  const levels = new Map<number, boolean>();
  const listeners = new Map<number, Set<(pin: number, state: boolean) => void>>();
  const pinManager = {
    onPinChange(pin: number, callback: (pin: number, state: boolean) => void) {
      const callbacks = listeners.get(pin) ?? new Set();
      callbacks.add(callback);
      listeners.set(pin, callbacks);
      return () => {
        callbacks.delete(callback);
      };
    },
  };
  const trace = (pin: string) => pins[pin] ?? null;
  // Use the real resolver: even an unwired COM pin returns an object reporting FLOATING.
  const resolve = (pin: string) =>
    createDefaultPinResolver(
      'display',
      pin,
      {
        components: [],
        boards: [],
        wires: [],
        ownerBoard: null,
        subscribeArduinoPin: pinManager.onPinChange,
        readArduinoPin: (number) => levels.get(number) ?? false,
      },
      (_id, name) => trace(name),
    );
  const element = { digits, values: Array(digits * 8).fill(0) };
  const cleanup = PartSimulationRegistry.get('7segment')!.attachEvents!(
    element as unknown as HTMLElement,
    { pinManager } as never,
    trace,
    'display',
    resolve,
  );
  return {
    element,
    cleanup,
    set(pin: number, level: boolean) {
      levels.set(pin, level);
      for (const callback of listeners.get(pin) ?? []) callback(pin, level);
      vi.advanceTimersByTime(10);
    },
  };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('single-digit common cathode display', () => {
  it.each(['COM.1', 'COM.2'])(
    'lights all digits with grounded %s and the other common unwired',
    (common) => {
      const display = attach({ [common]: -1, A: 2, B: 3, C: 4, D: 5, E: 6, F: 7, G: 8 });
      for (const pattern of [0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f]) {
        const expected = Array.from({ length: 7 }, (_, segment) => (pattern >> segment) & 1);
        expected.forEach((value, segment) => display.set(segment + 2, Boolean(value)));
        expect(display.element.values).toEqual([...expected, 0]);
      }
      display.cleanup();
      display.set(2, false);
      expect(display.element.values[0]).toBe(1);
    },
  );

  it('preserves independently selected multiplexed digits', () => {
    const display = attach({ DIG1: 10, DIG2: 11, A: 2, B: 3 }, 2);
    display.set(2, true);
    display.set(10, true);
    display.set(10, false);
    display.set(2, false);
    display.set(3, true);
    display.set(11, true);
    expect(display.element.values).toEqual([1, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]);
    display.cleanup();
  });
});
