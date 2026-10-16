import { motion } from "framer-motion";
import { Link } from "react-router-dom";

const QUICK_START = [
  {
    title: "Оцените общую картину",
    text: "Откройте аналитику и выберите нужные площадки и период. Так все блоки покажут данные только по выбранной выборке.",
    to: "/analytics",
    action: "Перейти к аналитике",
  },
  {
    title: "Посмотрите сообщения аудитории",
    text: "Во вкладке «Темы обсуждений» собраны комментарии, которые система распознала как жалобы, просьбы и значимые сигналы.",
    to: "/analytics",
    action: "Открыть темы обсуждений",
  },
  {
    title: "Проверьте географию проблем",
    text: "Во вкладке «Карта болей» видны только адресные кейсы, которые прошли геокодинг и получили координату.",
    to: "/analytics",
    action: "Открыть карту",
  },
  {
    title: "Сверьте историю публикаций",
    text: "На странице истории можно посмотреть, какие публикации выходили в сообществах и когда они были опубликованы.",
    to: "/calendar",
    action: "Открыть историю",
  },
];

const SECTIONS = [
  {
    title: "Главная",
    text: "Короткая сводка по собранным комментариям: сколько данных собрано, сколько прошло классификацию, сколько обращений выделено и сколько получило ответ организации.",
  },
  {
    title: "Аналитика",
    text: "Основной рабочий раздел. Здесь переключаются «Темы обсуждений», «Карта болей» и «Статистика». Фильтр по площадкам сверху влияет на все эти вкладки.",
  },
  {
    title: "Темы обсуждений",
    text: "Список категорий, конкретных проблем и примеров комментариев. Если у комментария есть ответ организации, рядом отображается кликабельная отметка.",
  },
  {
    title: "Карта болей",
    text: "Географическое отображение адресных кейсов. На карту попадают только те обращения, для которых система смогла определить координату.",
  },
  {
    title: "Статистика",
    text: "Постовая статистика: публикации, просмотры, реакции, комментарии и динамика по выбранным площадкам.",
  },
  {
    title: "История публикаций",
    text: "Календарное отображение публикаций по сообществам. Можно переключать месяц и неделю, фильтровать по пабликам и открывать опубликованный пост.",
  },
  {
    title: "Настройки",
    text: "Для обычного пользователя здесь находится аккаунт, информация об организации и смена пароля.",
  },
];

const TROUBLESHOOTING = [
  "Если данных мало или пусто, проверьте выбранный период и фильтр по площадкам.",
  "Если адрес не появился на карте, значит кейс не прошел геокодинг или не был признан адресным.",
  "Если комментарий выглядит важным, но не попал в нужную категорию, сообщите администратору: категории и правила проверки настраиваются отдельно.",
  "Если ссылка на ответ организации не отображается, значит система не нашла связанный официальный ответ.",
];

export function GuidePage() {
  return (
    <motion.section
      key="guide"
      className="content-page guide-page"
      initial={{ opacity: 0, y: 18, filter: "blur(4px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: -14, filter: "blur(3px)" }}
      transition={{ duration: 0.45 }}
    >
      <div className="content-page-head">
        <div>
          <h2 className="content-page-title">Руководство</h2>
          <p className="muted content-page-lead">
            Короткая инструкция по основным разделам системы для пользователя, который работает с аналитикой и публикациями.
          </p>
        </div>
      </div>

      <section className="guide-section">
        <div className="guide-section-head">
          <h3>Быстрый старт</h3>
          <p className="muted">Минимальный маршрут, чтобы понять, что происходит в сообществах.</p>
        </div>
        <div className="guide-steps">
          {QUICK_START.map((item, index) => (
            <article className="guide-step" key={item.title}>
              <span className="guide-step-number">{index + 1}</span>
              <div>
                <h4>{item.title}</h4>
                <p>{item.text}</p>
                <Link className="guide-link" to={item.to}>
                  {item.action}
                </Link>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="guide-section">
        <div className="guide-section-head">
          <h3>Что где смотреть</h3>
          <p className="muted">Краткая карта разделов без администраторских функций.</p>
        </div>
        <div className="guide-directory">
          {SECTIONS.map((section) => (
            <article className="guide-directory-item" key={section.title}>
              <h4>{section.title}</h4>
              <p>{section.text}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="guide-section">
        <div className="guide-section-head">
          <h3>Если что-то не сходится</h3>
          <p className="muted">Самые частые причины, почему на экране может быть меньше данных, чем ожидается.</p>
        </div>
        <ul className="guide-checklist">
          {TROUBLESHOOTING.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </section>
    </motion.section>
  );
}
