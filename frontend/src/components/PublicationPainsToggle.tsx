import { useState } from "react";

import { usePublicationPainsByUrl } from "../hooks/usePublicationPainsByUrl";

type PublicationPainsToggleProps = {
  authToken: string | null;
  url: string;
};

export function PublicationPainsToggle({ authToken, url }: PublicationPainsToggleProps) {
  const [expanded, setExpanded] = useState(false);
  const publicationPainsQuery = usePublicationPainsByUrl(authToken, url, expanded);
  const items = publicationPainsQuery.data ?? [];

  return (
    <>
      <button
        type="button"
        className="analytics-post-link"
        onClick={() => setExpanded((prev) => !prev)}
      >
        {expanded ? "Скрыть боли" : "Какие боли"}
      </button>
      {expanded && publicationPainsQuery.isFetching && (
        <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>Загрузка...</p>
      )}
      {expanded && !publicationPainsQuery.isFetching && (
        <div className="analytics-post-pains">
          {items.length === 0 ? (
            <p className="muted" style={{ fontSize: 12 }}>Комментарии этого поста не привязаны ни к одной боли.</p>
          ) : (
            <ul>
              {items.map((item) => (
                <li key={item.pain_id}>
                  <strong>{item.pain_title}</strong>
                  <span className="muted"> · {item.comments_count} комм.</span>
                  {item.pain_category && <span className="muted"> · {item.pain_category}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </>
  );
}
