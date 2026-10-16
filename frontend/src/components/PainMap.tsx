import { useEffect, useMemo, useRef, useState } from "react";
import { apiDeleteAddressCases, apiGetPainMap, apiGetCaseComments, type PainMapPoint, type CaseComment } from "../api";
import { stripVkMentions } from "../app/utils";
import {
  KRASNOYARSK_MUNICIPALITIES,
  normalizeMunicipality,
} from "../app/krasnoyarskMunicipalities";
import { KRASNOYARSK_KRAI_POLYGONS } from "../app/krasnoyarskKraiBorder";
import { MUNICIPALITY_BORDERS } from "../app/municipalityBorders";
import { useMe } from "../hooks/useMe";
import { isOkLink, isTelegramLink } from "../api";

const YANDEX_KEY = (import.meta.env.VITE_YANDEX_MAPS_KEY as string | undefined) ?? "";
const YANDEX_SRC = `https://api-maps.yandex.ru/2.1/?apikey=${YANDEX_KEY}&lang=ru_RU`;
const YANDEX_KEY_ERROR = "API-ключ Яндекс.Карт не настроен. Карта недоступна.";

declare global {
  interface Window { ymaps?: any }
}

function loadYmaps(): Promise<any> {
  if (window.ymaps?.ready) return new Promise((res) => window.ymaps.ready(() => res(window.ymaps)));
  return new Promise((resolve, reject) => {
    let s = document.querySelector<HTMLScriptElement>(`script[src="${YANDEX_SRC}"]`);
    if (!s) {
      s = document.createElement("script");
      s.src = YANDEX_SRC;
      document.head.appendChild(s);
    }
    const onLoad = () => {
      if (window.ymaps?.ready) {
        window.ymaps.ready(() => resolve(window.ymaps));
      } else if (window.ymaps) {
        resolve(window.ymaps);
      } else {
        reject(new Error("Яндекс.Карты загрузились, но API не доступен. Проверьте API-ключ."));
      }
    };
    s.addEventListener("load", onLoad);
    s.addEventListener("error", () => reject(new Error("Не удалось загрузить Яндекс.Карты")));
  });
}

/** Строит обводку Красноярского края из вшитого контура (OSM relation 190090).
 *
 *  Не зависит от модуля ymaps.borders: он есть не у всякого ключа, поэтому
 *  геометрию держим локально. Возвращает коллекцию полигонов (материк + острова)
 *  с общим стилем; null — только если что-то пошло совсем не так.
 */
function createKrasnoyarskBorder(ymaps: any): any | null {
  try {
    const collection = new ymaps.GeoObjectCollection(null, {
      // Заметная обводка + лёгкая заливка, чтобы край именно «выделялся».
      fillColor: "#2f6bff",
      fillOpacity: 0.06,
      strokeColor: "#2f6bff",
      strokeWidth: 3,
      strokeOpacity: 0.9,
      // Обводка/заливка не должны перехватывать клики по меткам под ними.
      interactivityModel: "default#transparent",
    });
    for (const rings of KRASNOYARSK_KRAI_POLYGONS) {
      collection.add(new ymaps.Polygon(rings, {}, {}));
    }
    return collection;
  } catch (error) {
    console.warn("[pain-map] не удалось построить границу края:", error);
    return null;
  }
}

// Базовый и подсвеченный стиль границы муниципального образования.
const MO_BASE_STYLE = {
  strokeColor: "#6a7a90",
  strokeWidth: 1,
  strokeOpacity: 0.5,
  fillColor: "#6a7a90",
  fillOpacity: 0.03,
};
const MO_SELECTED_STYLE = {
  strokeColor: "#22c55e",
  strokeWidth: 2.5,
  strokeOpacity: 0.95,
  fillColor: "#22c55e",
  fillOpacity: 0.1,
};

/** Строит границы муниципальных образований из вшитого geojson.
 *
 *  Каждый МО — своя под-коллекция полигонов (материк + острова одной единицы),
 *  чтобы её можно было целиком подсветить/кликнуть. Возвращает карту key→коллекция
 *  (key = normalizeMunicipality(NAME), совпадает с ключами krasnoyarskMunicipalities).
 */
function createMunicipalityBorders(ymaps: any): Map<string, any> | null {
  try {
    const byKey = new Map<string, any>();
    for (const mo of MUNICIPALITY_BORDERS) {
      const sub = new ymaps.GeoObjectCollection(null, { ...MO_BASE_STYLE });
      for (const rings of mo.polygons) {
        sub.add(new ymaps.Polygon(rings, { hintContent: mo.name }, {}));
      }
      byKey.set(mo.key, sub);
    }
    return byKey;
  } catch (error) {
    console.warn("[pain-map] не удалось построить границы МО:", error);
    return null;
  }
}

/** Центр тяжести кольца полигона. Координаты [lat, lon], площадь — для выбора
 *  главного контура МО (у островных единиц полигонов несколько). */
function ringCentroid(ring: number[][]): { lat: number; lon: number; area: number } {
  let twiceArea = 0;
  let lat = 0;
  let lon = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [latJ, lonJ] = ring[j];
    const [latI, lonI] = ring[i];
    const cross = lonJ * latI - lonI * latJ;
    twiceArea += cross;
    lon += (lonJ + lonI) * cross;
    lat += (latJ + latI) * cross;
  }
  if (!twiceArea) return { lat: ring[0][0], lon: ring[0][1], area: 0 };
  return { lat: lat / (3 * twiceArea), lon: lon / (3 * twiceArea), area: Math.abs(twiceArea / 2) };
}

// key МО -> точка для подписи: центр самого крупного контура единицы.
const MUNICIPALITY_CENTROIDS = new Map<string, [number, number]>(
  MUNICIPALITY_BORDERS.map((mo) => {
    let best = { lat: 0, lon: 0, area: -1 };
    for (const polygon of mo.polygons) {
      const centroid = ringCentroid(polygon[0]);
      if (centroid.area > best.area) best = centroid;
    }
    return [mo.key, [best.lat, best.lon] as [number, number]];
  }),
);

// Любое написание МО -> ключ его границы, чтобы разные варианты названия из
// данных сходились в один муниципалитет.
const BORDER_KEY_BY_ALIAS = new Map<string, string>(
  MUNICIPALITY_BORDERS.map((mo) => [mo.key, mo.key]),
);
for (const municipality of KRASNOYARSK_MUNICIPALITIES) {
  const borderKey = municipality.keys.find((key) => MUNICIPALITY_CENTROIDS.has(key));
  if (!borderKey) continue;
  for (const key of municipality.keys) {
    if (!BORDER_KEY_BY_ALIAS.has(key)) BORDER_KEY_BY_ALIAS.set(key, borderKey);
  }
}

/** Короткое имя МО для подписи на карте: «Богучанский», «Норильск». */
function shortMunicipalityName(name: string): string {
  return name
    .replace(/\s*муниципальный\s+(округ|район)\s*/i, " ")
    .replace(/\s*городской\s+округ\s*/i, " ")
    .replace(/\s*(округ|район)\s*$/i, "")
    .replace(/\s+/g, " ")
    .trim();
}

function mentionBreakpoints(max: number): { mediumStart: number; highStart: number } {
  const safeMax = Math.max(1, max);
  return {
    mediumStart: Math.max(2, Math.ceil(safeMax * 0.3)),
    highStart: Math.max(3, Math.ceil(safeMax * 0.6)),
  };
}

function color(count: number, max: number): string {
  const { mediumStart, highStart } = mentionBreakpoints(max);
  if (count >= highStart) return "#d64545";
  if (count >= mediumStart) return "#d9772b";
  return "#2f6bff";
}

function rangeLabel(start: number, end: number): string {
  return start === end ? `${start}` : `${start}-${end}`;
}

function legendItems(max: number): { color: string; label: string }[] {
  const { mediumStart, highStart } = mentionBreakpoints(max);
  const lowEnd = Math.max(1, mediumStart - 1);
  const mediumEnd = Math.max(mediumStart, highStart - 1);

  return [
    { color: "#2f6bff", label: `Мало (${rangeLabel(1, lowEnd)})` },
    { color: "#d9772b", label: `Средне (${rangeLabel(mediumStart, mediumEnd)})` },
    { color: "#d64545", label: `Много (${highStart}+)` },
  ];
}

type Props = {
  token: string;
  period: string;
  publicSocialLinkId?: string | null;
  municipalityName?: string | null;
  targetCaseName?: string | null;
  /** Клик по границе округа — то же, что галочка в фильтре муниципалитетов. */
  onMunicipalityToggle?: (label: string) => void;
};

const OTHER_PROBLEM_TYPE = "__other_category__";
const PROBLEM_TYPE_OPTIONS = [
  { value: "ЖКХ и городская среда", label: "ЖКХ и городская среда" },
  { value: "Дороги и транспорт", label: "Дороги и транспорт" },
  { value: "Социальная сфера", label: "Социальная сфера" },
  { value: "Экология и санитарное состояние", label: "Экология и санитарное состояние" },
  { value: "Управление и обратная связь", label: "Управление и обратная связь" },
  { value: "Безопасность и ЧС", label: "Безопасность и ЧС" },
  { value: "Экономика, торговля и регулирование", label: "Экономика, торговля и регулирование" },
  { value: "Связь и цифровая инфраструктура", label: "Связь и цифровая инфраструктура" },
  { value: OTHER_PROBLEM_TYPE, label: "Другая категория" },
];
const MUNICIPALITY_GROUP_MAX_ZOOM = 7;
const MAP_INITIAL_CENTER: [number, number] = [57.0, 93.5];
const MAP_INITIAL_ZOOM = 5;
const MAP_MIN_ZOOM = 4;
const MAP_MAX_ZOOM = 16;
const MAP_RESTRICT_BOUNDS: [[number, number], [number, number]] = [[36.0, 5.0], [86.0, 205.0]];
const MAP_CLEANUP_CSS = `
.pain-map-canvas ymaps,
.pain-map-canvas ymaps * {
  box-sizing: content-box !important;
}

.pain-map-canvas img {
  border: 0 !important;
  box-shadow: none !important;
  max-width: none !important;
}

.pain-map-canvas [class*="copyright"],
.pain-map-canvas [class*="gotoymaps"],
.pain-map-canvas [class*="gototech"],
.pain-map-canvas [class*="map-copyrights"],
.pain-map-canvas [class*="route-panel"],
.pain-map-canvas [class*="search"],
.pain-map-canvas [class*="traffic"],
.pain-map-canvas [class*="controls-pane"],
.pain-map-canvas [class*="float-button"],
.pain-map-canvas [class*="promo"] {
  display: none !important;
  opacity: 0 !important;
  pointer-events: none !important;
}

/* Маркер боли: цветной круг с числом упоминаний. Позиционируется от центра
   геоточки (левый-верх сдвинут в шаблоне), поэтому кружок сидит ровно на точке. */
.pain-pin {
  position: absolute;
  border-radius: 50%;
  color: #fff;
  text-align: center;
  font-weight: 700;
  font-size: 11px;
  border: 1px solid rgba(255, 255, 255, 0.75);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  cursor: pointer;
  box-sizing: border-box;
}

/* Выбранный маркер — белое кольцо снаружи для подсветки. */
.pain-pin.pain-pin--selected {
  border: 3px solid #fff;
  box-shadow: 0 0 0 3px #2f6bff, 0 2px 6px rgba(0, 0, 0, 0.4);
}

/* Число упоминаний на территории МО. Обводка текста вместо подложки —
   чтобы не перекрывать карту; название только в подсказке при наведении. */
.pain-area-pin {
  position: absolute;
  transform: translate(-50%, -50%);
  font-size: 15px;
  font-weight: 800;
  line-height: 1;
  cursor: pointer;
  text-shadow:
    -1px -1px 0 #fff, 1px -1px 0 #fff, -1px 1px 0 #fff, 1px 1px 0 #fff,
    0 0 4px rgba(255, 255, 255, 0.9);
}

/* Выбранная территория МО — яркая подсветка текста. */
.pain-area-pin.pain-pin--selected {
  color: #f59e0b !important;
  font-size: 17px;
  text-shadow:
    -1px -1px 0 #fff, 1px -1px 0 #fff, -1px 1px 0 #fff, 1px 1px 0 #fff,
    0 0 8px rgba(245, 158, 11, 0.6);
}
`;

// кликабельная зона подписи: она центрируется по точке средствами CSS
const AREA_LABEL_SHAPE = { type: "Rectangle", coordinates: [[-18, -11], [18, 11]] };

type MapDisplayPoint = PainMapPoint & {
  aggregationLevel?: "region" | "municipality";
  childPointCount?: number;
};

type FilterMenu = "problem" | null;
type DropdownOption = { value: string; label: string };

function mapCacheKey(
  token: string,
  period: string,
  linkId: string | null,
  problemType: string | null,
): string {
  // Набор точек один на период/площадку/категорию. Муниципалитет — это
  // визуальный срез этого набора, а не причина снова загружать карту.
  return JSON.stringify([token, period, linkId || "", problemType || ""]);
}

type FilterDropdownProps = {
  value: string;
  options: DropdownOption[];
  open: boolean;
  onToggle: () => void;
  onChange: (value: string) => void;
};

function FilterDropdown({ value, options, open, onToggle, onChange }: FilterDropdownProps) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [menuMaxHeight, setMenuMaxHeight] = useState(260);
  const selected = options.find((option) => option.value === value) ?? options[0];

  useEffect(() => {
    if (!open) return;

    function updateMenuMaxHeight() {
      const rect = buttonRef.current?.getBoundingClientRect();
      if (!rect) return;
      const available = Math.floor(window.innerHeight - rect.bottom - 12);
      setMenuMaxHeight(Math.max(56, Math.min(260, available)));
    }

    updateMenuMaxHeight();
    window.addEventListener("resize", updateMenuMaxHeight);
    window.addEventListener("scroll", updateMenuMaxHeight, true);
    return () => {
      window.removeEventListener("resize", updateMenuMaxHeight);
      window.removeEventListener("scroll", updateMenuMaxHeight, true);
    };
  }, [open]);

  return (
    <div style={{ position: "relative", minWidth: 0 }}>
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={onToggle}
        style={{
          width: "100%",
          minHeight: 38,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
          border: "1px solid var(--border)",
          borderRadius: 8,
          background: "var(--surface-card)",
          color: "var(--text-primary)",
          cursor: "pointer",
          padding: "8px 11px",
          textAlign: "left",
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{selected?.label}</span>
        <span aria-hidden="true" style={{ color: "var(--text-muted)", fontSize: 10 }}>▼</span>
      </button>
      {open && (
        <div
          role="listbox"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            right: 0,
            zIndex: 20,
            maxHeight: menuMaxHeight,
            overflowY: "auto",
            border: "1px solid var(--border)",
            borderRadius: 8,
            background: "var(--surface-card)",
            boxShadow: "0 14px 34px rgba(15, 32, 53, 0.18)",
            padding: 4,
          }}
        >
          {options.map((option) => {
            const active = option.value === value;
            return (
              <button
                key={option.value || "__all__"}
                type="button"
                role="option"
                aria-selected={active}
                onClick={() => onChange(option.value)}
                style={{
                  width: "100%",
                  border: 0,
                  borderRadius: 6,
                  background: active ? "color-mix(in srgb, var(--accent-ui) 12%, transparent)" : "transparent",
                  color: "var(--text-primary)",
                  cursor: "pointer",
                  fontWeight: active ? 700 : 500,
                  padding: "8px 9px",
                  textAlign: "left",
                }}
              >
                {option.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** Точки в адресном виде показываем, когда МО выбран или карта приближена. */
function isAddressView(zoom: number, municipality: string | null): boolean {
  return municipality != null || zoom > MUNICIPALITY_GROUP_MAX_ZOOM;
}

function municipalityKeyOf(point: PainMapPoint): string {
  return normalizeMunicipality(point.municipality || point.district || point.locality || "");
}

/**
 * Геокодер может записать город в locality, а округ — в municipality/district.
 * Сверяем все три поля с ключами выбранного МО, поэтому «Красноярск» не теряет
 * точки из-за варианта адресной иерархии в исходном комментарии.
 */
function belongsToMunicipality(point: PainMapPoint, municipality: string | null, municipalityByKey: Map<string, string>): boolean {
  if (!municipality) return true;
  const selected = new Set(municipality.split(",").map((name) => name.trim()).filter(Boolean));
  if (selected.size === 0) return true;
  return [point.municipality, point.district, point.locality]
    .map(normalizeMunicipality)
    .some((key) => selected.has(municipalityByKey.get(key) || ""));
}

/** Общий вид карты: подпись с числом упоминаний на территории КАЖДОГО МО, в том
 *  числе с нулём. Адреса-точки — при приближении или выборе МО; точки без
 *  опознанного муниципалитета остаются кружками. */
function pointsForView(
  points: PainMapPoint[],
  zoom: number,
  municipality: string | null,
): MapDisplayPoint[] {
  if (isAddressView(zoom, municipality)) return points;
  const totals = new Map<string, { count: number; cases: Set<string>; size: number }>();
  const ungrouped: MapDisplayPoint[] = [];
  for (const point of points) {
    const borderKey = BORDER_KEY_BY_ALIAS.get(municipalityKeyOf(point));
    if (!borderKey) {
      ungrouped.push(point);
      continue;
    }
    const total = totals.get(borderKey) ?? { count: 0, cases: new Set<string>(), size: 0 };
    total.count += point.count;
    total.size += 1;
    point.cases.forEach((caseName) => total.cases.add(caseName));
    totals.set(borderKey, total);
  }

  const labels = MUNICIPALITY_BORDERS.flatMap((mo): MapDisplayPoint[] => {
    const total = totals.get(mo.key);
    if (!total || total.count === 0) return [];
    const [lat, lon] = MUNICIPALITY_CENTROIDS.get(mo.key) as [number, number];
    return [{
      name: shortMunicipalityName(mo.name),
      district: mo.name,
      lat,
      lon,
      count: total.count,
      cases: Array.from(total.cases),
      aggregationLevel: "municipality",
      childPointCount: total.size,
    }];
  });

  return [...labels, ...ungrouped].sort((left, right) => right.count - left.count);
}

function findPointByCaseName(points: PainMapPoint[], targetCaseName?: string | null): PainMapPoint | null {
  const normalizedTarget = (targetCaseName || "").replace(/\s+/g, " ").trim().toLocaleLowerCase("ru");
  if (!normalizedTarget) return null;
  return points.find((point) => point.cases.some((caseName) => (
    caseName.replace(/\s+/g, " ").trim().toLocaleLowerCase("ru") === normalizedTarget
  ))) ?? null;
}

function OfficialResponseLink({ comment }: { comment: CaseComment }) {
  const label = comment.has_official_response ? "ЕСТЬ ОТВЕТ ОРГАНИЗАЦИИ" : "НЕТ ОТВЕТА ОРГАНИЗАЦИИ";
  if (comment.has_official_response && comment.official_response_url) {
    return (
      <a
        href={comment.official_response_url}
        target="_blank"
        rel="noreferrer"
        title={comment.official_response_text || label}
        style={{
          color: "#3f9b5f",
          fontSize: 11,
          fontWeight: 800,
          textDecoration: "underline",
          textUnderlineOffset: 3,
        }}
      >
        {label}
      </a>
    );
  }
  return (
    <span style={{ color: "var(--text-muted)", fontSize: 11, fontWeight: 800 }}>
      {label}
    </span>
  );
}

export default function PainMap({
  token,
  period,
  publicSocialLinkId = null,
  municipalityName = null,
  targetCaseName = null,
  onMunicipalityToggle,
}: Props) {
  const meQuery = useMe(token);
  const mapRef = useRef<HTMLDivElement>(null);
  const filterBarRef = useRef<HTMLDivElement>(null);
  const pointsCacheRef = useRef<Map<string, PainMapPoint[]>>(new Map());
  const mapInstanceRef = useRef<any | null>(null);
  const markerRendererRef = useRef<(() => void) | null>(null);
  const [problemType, setProblemType] = useState<string | null>(null);
  const municipality = municipalityName ?? null;
  const [openFilter, setOpenFilter] = useState<FilterMenu>(null);
  const borderRef = useRef<any | null>(null);
  // key -> под-коллекция границ МО; строится один раз при готовности карты.
  const municipalityBordersRef = useRef<Map<string, any> | null>(null);
  const pinLayoutRef = useRef<any | null>(null);
  const areaLabelLayoutRef = useRef<any | null>(null);
  const markersRef = useRef<any | null>(null);
  // Максимум по видимым точкам — единая база для цвета маркеров И легенды.
  const [legendMax, setLegendMax] = useState(1);
  const [points, setPoints] = useState<PainMapPoint[] | null>(null);
  const [mapLoading, setMapLoading] = useState(false);
  const [error, setError] = useState<string>(!YANDEX_KEY ? YANDEX_KEY_ERROR : "");
  const [selected, setSelected] = useState<MapDisplayPoint | null>(null);
  const [comments, setComments] = useState<CaseComment[] | null>(null);
  const commentsRequestRef = useRef(0);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteMessage, setDeleteMessage] = useState("");
  const linkId = publicSocialLinkId ?? null;
  const isSuperadmin = meQuery.data?.role === "superadmin";
  const problemOptions: DropdownOption[] = [
    { value: "", label: "Все типы проблем" },
    ...PROBLEM_TYPE_OPTIONS,
  ];

  // Ключ (нормализованный район/город) -> официальный округ.
  const municipalityByKey = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of KRASNOYARSK_MUNICIPALITIES) {
      for (const key of m.keys) map.set(key, m.label);
    }
    return map;
  }, []);

  // Точки подгружаются один раз без муниципального SQL-фильтра. Фильтрация по
  // данным геокодера происходит сразу в браузере: карта остаётся на месте, а
  // для Красноярска учитываются и locality, и municipality/district.
  const displayPoints = useMemo(
    () => (points ?? []).filter((point) => belongsToMunicipality(point, municipality, municipalityByKey)),
    [points, municipality, municipalityByKey],
  );

  // Пока карта не отрисовала маркеры (legendMax обновится в renderMarkers),
  // показываем легенду от индивидуального максимума — как разумный старт.
  const initialMax = Math.max(1, ...(displayPoints ?? []).map((p) => p.count));
  const legendBase = legendMax > 1 ? legendMax : initialMax;

  useEffect(() => {
    let alive = true;
    commentsRequestRef.current += 1;
    setSelected(null);
    setComments(null);
    if (!YANDEX_KEY) {
      setPoints([]);
      setError(YANDEX_KEY_ERROR);
      setMapLoading(false);
      setSelected(null);
      setComments(null);
      return () => { alive = false; };
    }
    const cacheKey = mapCacheKey(token, period, linkId, problemType);
    const cached = pointsCacheRef.current.get(cacheKey);
    setError("");
    setMapLoading(true);
    if (cached) {
      setPoints(cached);
      setMapLoading(false);
      setSelected(null);
      setComments(null);
      return () => { alive = false; };
    }
    apiGetPainMap(token, period, linkId, problemType, null)
      .then((p) => {
        if (!alive) return;
        if (pointsCacheRef.current.size >= 30) pointsCacheRef.current.clear();
        pointsCacheRef.current.set(cacheKey, p);
        setPoints(p);
        setSelected(null);
        setComments(null);
      })
      .catch((e) => alive && setError(String(e?.message || e)))
      .finally(() => alive && setMapLoading(false));
    return () => { alive = false; };
  }, [token, period, linkId, problemType]);

  // При смене территории закрываем карточку старой точки, но не очищаем
  // существующие маркеры и не показываем повторную загрузку карты.
  useEffect(() => {
    commentsRequestRef.current += 1;
    setSelected(null);
    setComments(null);
  }, [municipality]);

  function openPoint(p: MapDisplayPoint) {
    const requestId = ++commentsRequestRef.current;
    setSelected(p);
    setComments(null);
    setDeleteMessage("");
    // Точка уже была отнесена к МО по результату геокодера. Не применяем к
    // примерам второй, текстовый фильтр: адрес в комментарии может быть
    // сокращён или записан в другой форме, из-за чего карточка точки иногда
    // оставалась без примеров.
    apiGetCaseComments(token, p.cases, period, linkId, problemType, null)
      .then((items) => { if (requestId === commentsRequestRef.current) setComments(items); })
      .catch(() => { if (requestId === commentsRequestRef.current) setComments([]); });
  }

  // Обработчики карты живут дольше рендера, поэтому свежие данные и колбэки
  // читаются из ref — карта не пересоздаётся при смене фильтров и выборе точки.
  const renderStateRef = useRef({ displayPoints, municipality, municipalityByKey, selected });
  renderStateRef.current = { displayPoints, municipality, municipalityByKey, selected };
  const openPointRef = useRef(openPoint);
  openPointRef.current = openPoint;
  const toggleMunicipalityRef = useRef(onMunicipalityToggle);
  toggleMunicipalityRef.current = onMunicipalityToggle;

  // Выбранный кликом округ подсвечиваем сразу, не дожидаясь новых точек.
  useEffect(() => {
    markerRendererRef.current?.();
  }, [municipality]);
  const handledTargetRef = useRef<string | null>(null);
  const mapEnabled = Boolean(YANDEX_KEY);

  function focusTarget() {
    const map = mapInstanceRef.current;
    if (!map || !targetCaseName || handledTargetRef.current === targetCaseName) return;
    const target = findPointByCaseName(renderStateRef.current.displayPoints ?? [], targetCaseName);
    if (!target) return;
    handledTargetRef.current = targetCaseName;
    map.setCenter([target.lat, target.lon], 13);
    markerRendererRef.current?.();
    openPointRef.current(target);
  }

  async function refreshPoints() {
    const nextPoints = await apiGetPainMap(token, period, linkId, problemType, null);
    pointsCacheRef.current.set(mapCacheKey(token, period, linkId, problemType), nextPoints);
    setPoints(nextPoints);
    return nextPoints;
  }

  async function confirmDeleteAddressCase() {
    if (!selected || selected.aggregationLevel || selected.cases.length === 0) return;
    setDeleteLoading(true);
    setDeleteMessage("");
    try {
      const result = await apiDeleteAddressCases(token, selected.cases);
      pointsCacheRef.current.clear();
      await refreshPoints();
      setSelected(null);
      setComments(null);
      setDeleteConfirmOpen(false);
      setDeleteMessage(
        result.updated_analyses > 0
          ? `Кейс снят с карты. Обновлено анализов: ${result.updated_analyses}.`
          : "Кейс уже не является адресным.",
      );
    } catch (error) {
      setDeleteMessage(error instanceof Error ? error.message : "Не удалось удалить адресный кейс.");
    } finally {
      setDeleteLoading(false);
    }
  }

  useEffect(() => {
    if (!openFilter) return;
    function handlePointerDown(event: PointerEvent) {
      if (!filterBarRef.current?.contains(event.target as Node)) {
        setOpenFilter(null);
      }
    }
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [openFilter]);

  useEffect(() => {
    return () => {
      commentsRequestRef.current += 1;
      if (mapInstanceRef.current && markerRendererRef.current) {
        mapInstanceRef.current.events.remove("boundschange", markerRendererRef.current);
      }
      if (mapInstanceRef.current) {
        mapInstanceRef.current.destroy();
      }
      mapInstanceRef.current = null;
      markerRendererRef.current = null;
      borderRef.current = null;
      municipalityBordersRef.current = null;
      pinLayoutRef.current = null;
      areaLabelLayoutRef.current = null;
      markersRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!mapEnabled || !mapRef.current) {
      if (mapInstanceRef.current && markerRendererRef.current) {
        mapInstanceRef.current.events.remove("boundschange", markerRendererRef.current);
      }
      if (mapInstanceRef.current) {
        mapInstanceRef.current.destroy();
      }
      mapInstanceRef.current = null;
      markerRendererRef.current = null;
      borderRef.current = null;
      municipalityBordersRef.current = null;
      pinLayoutRef.current = null;
      areaLabelLayoutRef.current = null;
      markersRef.current = null;
      return;
    }
    let disposed = false;
    setMapLoading(true);
    loadYmaps().then((ymaps) => {
      if (disposed || !mapRef.current) return;
      const map = mapInstanceRef.current ?? new ymaps.Map(
          mapRef.current,
          { center: MAP_INITIAL_CENTER, zoom: MAP_INITIAL_ZOOM, controls: [] },
          {
            avoidFractionalZoom: true,
            maxZoom: MAP_MAX_ZOOM,
            minZoom: MAP_MIN_ZOOM,
            restrictMapArea: MAP_RESTRICT_BOUNDS,
            suppressMapOpenBlock: true,
            yandexMapDisablePoiInteractivity: true,
          },
        );
      mapInstanceRef.current = map;
      map.options.set({
        avoidFractionalZoom: true,
        maxZoom: MAP_MAX_ZOOM,
        minZoom: MAP_MIN_ZOOM,
        restrictMapArea: MAP_RESTRICT_BOUNDS,
        suppressMapOpenBlock: true,
      });
      if (markerRendererRef.current) {
        map.events.remove("boundschange", markerRendererRef.current);
      }
      const renderMarkers = () => {
        const { displayPoints: currentPoints, municipality: currentMunicipality, selected: selectedPoint } = renderStateRef.current;
        const source = currentPoints ?? [];
        const zoom = map.getZoom();
        const visiblePoints = pointsForView(source, zoom, currentMunicipality);
        // Единая база цвета: и маркеры, и легенда считают от этого максимума.
        const max = Math.max(1, ...visiblePoints.map((p) => p.count));
        setLegendMax(max);

        // Границы лежат на карте постоянно: их пересоздание на каждый клик и
        // перезум и давало «подгрузку». Меняем только стиль выбранного МО.
        if (municipalityBordersRef.current) {
          // Округов может быть выбрано несколько: фильтр — строка через запятую.
          const selectedLabels = new Set(
            (currentMunicipality || "").split(",").map((name) => name.trim()).filter(Boolean),
          );
          for (const [key, sub] of municipalityBordersRef.current) {
            const label = municipalityByKey.get(key);
            const isSelected = label != null && selectedLabels.has(label);
            sub.options.set(isSelected ? MO_SELECTED_STYLE : MO_BASE_STYLE);
          }
        }

        const markers = markersRef.current;
        if (!markers) return;
        markers.removeAll();

        const layout = pinLayoutRef.current;
        const areaLayout = areaLabelLayoutRef.current;
        for (const p of visiblePoints) {
          const hint = p.aggregationLevel
            ? `${p.district || p.name}: ${p.count} упоминаний, ${p.childPointCount} адресов — клик для комментариев`
            : `${p.name}: ${p.count} — клик для комментариев`;
          const size = 18;
          const pinColor = color(p.count, max);
          // территория МО — подпись с числом, отдельный адрес — кружок
          const asArea = Boolean(p.aggregationLevel) && Boolean(areaLayout);
          const isPointSelected = selectedPoint && p.lat === selectedPoint.lat && p.lon === selectedPoint.lon;
          const pm = new ymaps.Placemark(
            [p.lat, p.lon],
            {
              hintContent: hint,
              pinColor,
              pinSize: size,
              pinShift: -Math.round(size / 2),
              pinLabel: p.count > 1 ? String(p.count) : "",
              areaCount: String(p.count),
              pinClass: isPointSelected ? "pain-pin--selected" : "",
            },
            asArea
              ? { iconLayout: areaLayout, iconShape: AREA_LABEL_SHAPE }
              : layout
                ? {
                    iconLayout: layout,
                    iconShape: { type: "Circle", coordinates: [0, 0], radius: Math.round(size / 2) },
                  }
                // Фолбэк, если кастомный layout недоступен: цветной кружок как раньше.
                : { preset: "islands#circleIcon", iconColor: pinColor },
          );
          pm.events.add("click", () => openPointRef.current(p));
          markers.add(pm);
        }
      };
      markerRendererRef.current = renderMarkers;
      map.events.add("boundschange", renderMarkers);

      // Слои строим один раз и держим на карте: контур края → границы МО → метки.
      if (!borderRef.current) {
        borderRef.current = createKrasnoyarskBorder(ymaps);
        if (borderRef.current) map.geoObjects.add(borderRef.current);
      }
      if (!pinLayoutRef.current && ymaps.templateLayoutFactory) {
        pinLayoutRef.current = ymaps.templateLayoutFactory.createClass(
          '<div class="pain-pin $[properties.pinClass]" style="left: $[properties.pinShift]px; top: $[properties.pinShift]px;' +
            ' width: $[properties.pinSize]px; height: $[properties.pinSize]px;' +
            ' line-height: $[properties.pinSize]px; background: $[properties.pinColor];">' +
            "$[properties.pinLabel]</div>",
        );
      }
      if (!areaLabelLayoutRef.current && ymaps.templateLayoutFactory) {
        areaLabelLayoutRef.current = ymaps.templateLayoutFactory.createClass(
          '<div class="pain-area-pin $[properties.pinClass]" style="color: $[properties.pinColor];">' +
            "$[properties.areaCount]</div>",
        );
      }
      if (!municipalityBordersRef.current) {
        const byKey = createMunicipalityBorders(ymaps);
        if (byKey) {
          // Клик по границе переключает округ в общем фильтре страницы, как
          // галочка в списке. Карту не двигаем: масштабом управляет пользователь.
          for (const [key, sub] of byKey) {
            const label = municipalityByKey.get(key);
            if (!label) continue;
            sub.events.add("click", () => toggleMunicipalityRef.current?.(label));
          }
          for (const sub of byKey.values()) map.geoObjects.add(sub);
          municipalityBordersRef.current = byKey;
        }
      }
      if (!markersRef.current) {
        markersRef.current = new ymaps.GeoObjectCollection(null, {});
        map.geoObjects.add(markersRef.current);
      }

      renderMarkers();
      focusTarget();
      setMapLoading(false);
    }).catch((e) => {
      if (!disposed) {
        setMapLoading(false);
        setError(String(e?.message || e));
      }
    });
    return () => {
      disposed = true;
      setMapLoading(false);
      if (mapInstanceRef.current && markerRendererRef.current) {
        mapInstanceRef.current.events.remove("boundschange", markerRendererRef.current);
        markerRendererRef.current = null;
      }
    };
  }, [mapEnabled]);

  // Смена фильтров/данных — только перерисовка меток, без пересоздания карты.
  useEffect(() => {
    markerRendererRef.current?.();
  }, [displayPoints, municipality]);

  useEffect(() => {
    focusTarget();
  }, [targetCaseName, displayPoints]);

  // Панель кейса меняет ширину контейнера — карте нужен пересчёт вьюпорта.
  useEffect(() => {
    mapInstanceRef.current?.container?.fitToViewport?.();
  }, [selected]);

  return (
    <div>
      <style>{MAP_CLEANUP_CSS}</style>
      <div
        ref={filterBarRef}
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          alignItems: "center",
          gap: 12,
          margin: "0 0 12px",
        }}
      >
        <FilterDropdown
          value={problemType ?? ""}
          options={problemOptions}
          open={openFilter === "problem"}
          onToggle={() => setOpenFilter((current) => current === "problem" ? null : "problem")}
          onChange={(value) => {
            setProblemType(value || null);
            setOpenFilter(null);
          }}
        />
      </div>
      {deleteMessage && (
        <p className={`message ${deleteMessage.includes("Не удалось") ? "error" : "success"}`} style={{ margin: "0 0 12px" }}>
          {deleteMessage}
        </p>
      )}
      {deleteConfirmOpen && selected && (
        <div className="org-modal-backdrop" role="dialog" aria-modal="true">
          <div className="org-modal">
            <h3 className="org-modal-title">Удалить адресный кейс с карты?</h3>
            <div className="org-modal-body">
              После подтверждения кейс перестанет считаться адресным во всей системе: он пропадет с карты и из адресных выборок.
              <div style={{ marginTop: 10, fontWeight: 700 }}>{selected.name}</div>
              {selected.cases.length > 1 && (
                <div className="muted" style={{ marginTop: 6, fontSize: 12 }}>
                  Будут сняты адресные признаки у {selected.cases.length} связанных названий кейса.
                </div>
              )}
            </div>
            <div className="org-modal-actions">
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => setDeleteConfirmOpen(false)}
                disabled={deleteLoading}
              >
                Отмена
              </button>
              <button
                type="button"
                className="btn btn-danger"
                onClick={confirmDeleteAddressCase}
                disabled={deleteLoading}
              >
                {deleteLoading ? "Удаляем..." : "Удалить с карты"}
              </button>
            </div>
          </div>
        </div>
      )}
      {error && (
        <div className="muted" style={{ padding: 16 }}>Карта недоступна: {error}</div>
      )}
      {!error && points?.length === 0 && (
        <div className="muted" role="status" style={{ padding: 16 }}>
          Нет обращений с координатами за выбранный период, площадку и муниципалитет. Можно выбрать другую территорию на карте или изменить фильтры.
        </div>
      )}
      {(
        <div className="pain-map-shell" style={{ display: "flex", gap: 12, alignItems: "stretch" }}>
          <div style={{ flex: 1, minWidth: 0, position: "relative" }}>
            <div
              ref={mapRef}
              className="pain-map-canvas"
              style={{
                minHeight: 420,
                height: "70vh",
                borderRadius: 12,
                overflow: "hidden",
                background: "var(--surface-inset)",
                border: "1px solid var(--border-soft)",
              }}
            />
            {mapLoading && (
              <div
                className="muted"
                style={{
                  position: "absolute",
                  inset: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  borderRadius: 12,
                  background: "var(--surface-card)",
                }}
              >
                Загрузка карты…
              </div>
            )}
            <div
              aria-label="Легенда карты"
              style={{
                position: "absolute",
                right: 14,
                top: 14,
                display: "grid",
                gap: 8,
                padding: "10px 12px",
                borderRadius: 10,
                background: "color-mix(in srgb, var(--surface-card) 92%, transparent)",
                border: "1px solid var(--border-soft)",
                boxShadow: "0 10px 24px rgba(15, 32, 53, 0.14)",
                backdropFilter: "blur(8px)",
                fontSize: 12,
                color: "var(--text-secondary)",
              }}
            >
              <div style={{ fontWeight: 700, color: "var(--text-primary)", marginBottom: 2 }}>
                По количеству упоминаний:
              </div>
              {legendItems(legendBase).map((item) => (
                <div key={item.color} style={{ display: "flex", alignItems: "center", gap: 8, whiteSpace: "nowrap" }}>
                  <span
                    aria-hidden="true"
                    style={{
                      width: 9,
                      height: 9,
                      borderRadius: "50%",
                      background: item.color,
                      boxShadow: `0 0 0 3px color-mix(in srgb, ${item.color} 18%, transparent)`,
                    }}
                  />
                  <span>{item.label}</span>
                </div>
              ))}
              <div style={{ marginTop: 4, lineHeight: 1.35, whiteSpace: "normal", maxWidth: 220 }}>
                Число в кружке — сумма упоминаний по территории. Приблизьте карту до
                отдельных адресов.
              </div>
            </div>
          </div>
          {selected && (
            <div style={{ width: 380, maxHeight: "70vh", overflow: "auto", background: "var(--surface-card)", border: "1px solid var(--border)", borderRadius: "var(--radius-card)", padding: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
                <strong>{selected.name}</strong>
                <button
                  type="button"
                  aria-label="Закрыть"
                  onClick={() => setSelected(null)}
                  style={{ border: 0, background: "transparent", cursor: "pointer", fontSize: 18, lineHeight: 1, padding: 2, color: "var(--text-secondary)" }}
                >
                  ×
                </button>
              </div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
                {selected.district ? `${selected.district} · ` : ""}{selected.count} упоминаний
                {selected.aggregationLevel && selected.childPointCount ? ` · ${selected.childPointCount} точек` : ""}
              </div>
              {isSuperadmin && !selected.aggregationLevel && (
                <button
                  type="button"
                  className="btn btn-danger-ghost"
                  onClick={() => setDeleteConfirmOpen(true)}
                  disabled={deleteLoading || selected.cases.length === 0}
                  style={{ width: "100%", marginBottom: 12 }}
                >
                  Удалить адресный кейс с карты
                </button>
              )}
              {isSuperadmin && selected.aggregationLevel && (
                <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
                  Приблизьте карту, чтобы удалить конкретный адресный кейс, а не агрегированную группу.
                </div>
              )}
              {comments === null && <div className="muted">Загрузка комментариев…</div>}
              {comments && comments.length === 0 && <div className="muted">Комментарии не найдены.</div>}
              {comments && comments.map((c, i) => (
                <div key={i} style={{ borderTop: i ? "1px solid var(--border-soft)" : 0, padding: "8px 0", fontSize: 13 }}>
                  <div style={{ lineHeight: 1.4 }}>{stripVkMentions(c.text)}</div>
                  <div className="muted" style={{ fontSize: 11, marginTop: 3, display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {c.category && <span style={{ color: "var(--accent-ui)" }}>{c.category}{c.subcategory ? ` · ${c.subcategory}` : ""}</span>}
                    {c.date && <span>{c.date.slice(0, 10)}</span>}
                    {c.public && <span>{c.public}</span>}
                    {(c.comment_url || c.url) && <a href={c.comment_url || c.url || "#"} target="_blank" rel="noreferrer">{isTelegramLink(c.comment_url || c.url || "") ? "TG" : isOkLink(c.comment_url || c.url || "") ? "OK" : /vk\.com\//i.test(c.comment_url || c.url || "") ? "VK" : "Источник"}</a>}
                  </div>
                  <div style={{ marginTop: 6 }}>
                    <OfficialResponseLink comment={c} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
