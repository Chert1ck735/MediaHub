import type { Dispatch, SetStateAction } from "react";
import { motion } from "framer-motion";

import type { PainListItem } from "../api";
import type { ContentEvent } from "../app/types";

export type ContentPageProps = {
  authToken: string;
  contentEvents: ContentEvent[];
  contentMessage: string;
  contentMessageType: string;
  contentPublishTargets: Record<string, string>;
  painItems: PainListItem[];
  publicationTargetOptions: Array<{ id: string; label: string }>;
  publishingItemId: string | null;
  deletingVkItemId: string | null;
  dataLoading: boolean;
  openAuth: (mode: "login") => void;
  onCreatePost: () => void;
  removeContentEvent: (id: string) => void;
  republishContentEvent: (id: string) => void;
  deleteVkPostForContent: (id: string) => void;
  setContentPublishTargets: Dispatch<SetStateAction<Record<string, string>>>;
};

export function ContentPage({
  authToken,
  contentEvents,
  contentMessage,
  contentMessageType,
  contentPublishTargets,
  painItems,
  publicationTargetOptions,
  publishingItemId,
  deletingVkItemId,
  dataLoading,
  openAuth,
  onCreatePost,
  removeContentEvent,
  republishContentEvent,
  deleteVkPostForContent,
  setContentPublishTargets,
}: ContentPageProps) {
  if (!authToken) {
    return (
      <motion.section key="content-guest" className="content-page"
        initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.35 }}>
        <div className="content-page-head">
          <div>
            <h2 className="content-page-title">Создание поста</h2>
            <p className="muted">Войдите в систему, чтобы создавать посты.</p>
          </div>
          <button className="btn btn-primary" type="button" onClick={() => openAuth("login")}>Войти</button>
        </div>
      </motion.section>
    );
  }

  if (dataLoading) {
    return (
      <motion.section key="content-loading" className="content-page"
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
        <p className="muted" style={{ textAlign: "center", marginTop: "3rem" }}>Загрузка данных…</p>
      </motion.section>
    );
  }

  return (
    <motion.section
      key="content"
      className="content-page"
      initial={{ opacity: 0, y: 18, filter: "blur(4px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: -14, filter: "blur(3px)" }}
      transition={{ duration: 0.45 }}
    >
      <div className="content-page-head">
        <div>
          <p className="eyebrow">От идеи до публикации</p>
          <h2 className="content-page-title">Студия контента</h2>
          <p className="muted content-page-lead">
            Опишите идею, создайте текст с ИИ и подготовьте его к публикации.
          </p>
        </div>
        <button className="btn btn-primary" type="button" onClick={onCreatePost}>
          Создать пост
        </button>
      </div>
      {contentEvents.length === 0 ? (
        <div className="workspace-empty content-empty"><span className="workspace-empty-symbol" aria-hidden="true">✧</span><h3>Ваша следующая публикация начинается здесь</h3><p>Добавьте тему и выберите сообщество — поможем подготовить первый текст.</p><button className="btn btn-primary" onClick={onCreatePost}>Создать первый пост</button></div>
      ) : (
        <div className="content-grid">
          {contentEvents.map((c) => (
            <article key={c.id} className="content-card">
              <div className="content-card-head">
                <h3>{c.title}</h3>
                <time dateTime={c.createdAt}>
                  {new Date(c.createdAt).toLocaleString("ru-RU", {
                    day: "numeric",
                    month: "short",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </time>
              </div>
              {c.attachmentDataUrl && (
                <img src={c.attachmentDataUrl} alt="" className="content-card-thumb" />
              )}
              {c.prompt && (
                <p className="content-card-meta">
                  <strong>Промпт:</strong> {c.prompt}
                </p>
              )}
              {c.strategyId && (
                <p className="content-card-meta">
                  <strong>Боль:</strong>{" "}
                  {painItems.find((pain) => pain.strategy_id === c.strategyId)?.title ?? "Связанная стратегия"}
                </p>
              )}
              {c.tone && (
                <p className="content-card-meta">
                  <strong>Тон:</strong> {c.tone}
                </p>
              )}
              {!!c.publicationLabels?.length && (
                <p className="content-card-meta">
                  <strong>Паблики:</strong> {c.publicationLabels.join(", ")}
                </p>
              )}
              {c.generatedText && (
                <p className="content-card-text">{c.generatedText}</p>
              )}
              {c.vkWallUrl && (
                <p className="content-card-vk">
                  <a href={c.vkWallUrl} target="_blank" rel="noreferrer">
                    Открыть пост в VK
                  </a>
                </p>
              )}
              {c.vkWallUrl && c.vkPostId && (
                <button
                  type="button"
                  className="link-btn danger"
                  onClick={() => deleteVkPostForContent(c.id)}
                  disabled={deletingVkItemId === c.id}
                >
                  {deletingVkItemId === c.id ? "Удаление..." : "Удалить пост из VK"}
                </button>
              )}
              {!c.vkWallUrl && (
                <>
                  <label className="content-card-meta">
                    <strong>Паблик:</strong>{" "}
                    <select
                      value={contentPublishTargets[c.id] ?? ""}
                      onChange={(e) =>
                        setContentPublishTargets((prev) => ({ ...prev, [c.id]: e.target.value }))
                      }
                    >
                      <option value="">Выберите паблик</option>
                      {publicationTargetOptions.map((option) => (
                        <option key={option.id} value={option.id}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => republishContentEvent(c.id)}
                    disabled={publishingItemId === c.id || !contentPublishTargets[c.id]}
                  >
                    {publishingItemId === c.id ? "Публикация..." : "Опубликовать в паблик"}
                  </button>
                </>
              )}
              {c.vkPublishError && <p className="content-card-error">{c.vkPublishError}</p>}
              <button type="button" className="link-btn danger" onClick={() => removeContentEvent(c.id)}>
                Удалить
              </button>
            </article>
          ))}
        </div>
      )}
      <p className={`message ${contentMessageType}`}>{contentMessage}</p>
    </motion.section>
  );
}
