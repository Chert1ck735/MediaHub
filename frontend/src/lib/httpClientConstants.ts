/** Ключ под которым JWT лежит в localStorage. Вынесен в отдельный файл,
 *  чтобы и httpClient, и api.ts могли его импортировать без циклической
 *  зависимости (api.ts → httpClient → api.ts при reuse JWT_KEY). */
export const JWT_KEY = "protechno_jwt";
