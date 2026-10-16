import { useEffect, useState } from "react";

/** Возвращает значение с задержкой — чтобы поиск не бил в API на каждую букву.
 *
 *  Это один из немногих законных useEffect: синхронизация с таймером (внешним
 *  по отношению к React). Cleanup обязателен — без него при быстром вводе
 *  накапливаются таймеры и отрабатывает устаревший.
 */
export function useDebounce<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
