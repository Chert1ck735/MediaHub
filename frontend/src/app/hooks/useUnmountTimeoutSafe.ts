/**
 * Хук для безопасных одноразовых setTimeout, привязанных к жизни компонента.
 *
 * Зачем: голый `setTimeout(() => setState(...), 120)` в onBlur / onClick живёт
 * сам по себе — если компонент размонтировался раньше срабатывания, React
 * вызовет setState на мёртвом компоненте (предупреждение в консоли + утечка
 * замыкания, удерживающего ссылки на старый компонент).
 *
 * Использование:
 *   const setTimeoutSafe = useUnmountTimeoutSafe();
 *   <input onBlur={() => setTimeoutSafe(() => setFocused(false), 120)} />
 *
 * Все таймеры автоматически отменяются при размонтировании компонента.
 */
import { useCallback, useEffect, useRef } from "react";

export function useUnmountTimeoutSafe() {
  const timersRef = useRef<Set<number>>(new Set());

  useEffect(
    () => () => {
      timersRef.current.forEach((id) => window.clearTimeout(id));
      timersRef.current.clear();
    },
    [],
  );

  return useCallback((cb: () => void, ms: number) => {
    const id = window.setTimeout(() => {
      timersRef.current.delete(id);
      cb();
    }, ms);
    timersRef.current.add(id);
    return id;
  }, []);
}
