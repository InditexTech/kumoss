// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import ButtonBase from "@mui/material/ButtonBase";
import Fade from "@mui/material/Fade";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useAuth } from "@/contexts/AuthContext";
import { listUserSessions } from "@/services/core/sessions";
import { getCachedSessions } from "@/services/core/sessionsCache";
import useDragScroll from "@/hooks/useDragScroll";
import type { UserSessionInfo } from "@/types/api";
import SessionCard from "./SessionCard";
import styles from "./UserSessionsHistory.module.css";

interface UserSessionsHistoryProps {
  pageSize?: number;
  onSelectSession?: (session: UserSessionInfo) => void;
}

export default function UserSessionsHistory({
  pageSize = 20,
  onSelectSession,
}: UserSessionsHistoryProps) {
  const { user } = useAuth();
  const navigate = useNavigate();
  const drag = useDragScroll<HTMLDivElement>();
  const [sessions, setSessions] = useState<UserSessionInfo[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loaded, setLoaded] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  useEffect(() => {
    if (!user?.username) return;
    const cached = getCachedSessions();
    if (cached) {
      setSessions(cached.sessions);
      setTotal(cached.total);
      setPage(1);
      setLoaded(true);
      return;
    }
    let cancelled = false;
    listUserSessions(user.username, { page: 1, page_size: pageSize })
      .then((res) => {
        if (!cancelled) {
          setSessions(res.items);
          setTotal(res.total);
          setPage(1);
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [user?.username, pageSize]);

  const loadMore = useCallback(() => {
    if (!user?.username || loadingMore) return;
    const nextPage = page + 1;
    setLoadingMore(true);
    listUserSessions(user.username, { page: nextPage, page_size: pageSize })
      .then((res) => {
        setSessions((prev) => [...prev, ...res.items]);
        setTotal(res.total);
        setPage(nextPage);
      })
      .catch(() => {})
      .finally(() => setLoadingMore(false));
  }, [user?.username, page, pageSize, loadingMore]);

  const hasMore = total > sessions.length;

  if (!loaded) return null;

  return (
    <Fade in timeout={600}>
      <Box className={styles.timeline}>
        <Box className={styles.header}>
          <Typography variant="h5" component="span" className={styles.title}>
            Sessions
          </Typography>
          <Stack direction="row" alignItems="center" spacing={2}>
            <ButtonBase
              className={styles.viewAll}
              onClick={() => navigate("/user/sessions")}
            >
              <Typography variant="subtitle2" component="span">
                View all
              </Typography>
            </ButtonBase>
            <ButtonBase
              className={styles.moreButton}
              onClick={loadMore}
              disabled={!hasMore || loadingMore}
            >
              <Typography variant="subtitle2" component="span">
                {loadingMore ? "Loading..." : "More"}
              </Typography>
            </ButtonBase>
          </Stack>
        </Box>
        <div
          className={styles.cardRow}
          ref={drag.ref}
          onPointerDown={drag.onPointerDown}
          onPointerMove={drag.onPointerMove}
          onPointerUp={drag.onPointerUp}
          onClickCapture={drag.onClickCapture}
        >
          {sessions.length === 0 ? (
            <Typography
              variant="h4"
              component="div"
              className={styles.emptyCard}
            >
              No previous sessions found
            </Typography>
          ) : (
            sessions.map((s) => (
              <SessionCard
                key={s.session_id}
                session={s}
                onClick={onSelectSession}
              />
            ))
          )}
        </div>
      </Box>
    </Fade>
  );
}
