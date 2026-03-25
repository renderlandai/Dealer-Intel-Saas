type UpgradePayload = { title: string; message: string };
type Listener = (payload: UpgradePayload) => void;

const listeners = new Set<Listener>();

export const upgradeEvents = {
  emit(payload: UpgradePayload) {
    listeners.forEach((fn) => fn(payload));
  },
  subscribe(fn: Listener) {
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  },
};
