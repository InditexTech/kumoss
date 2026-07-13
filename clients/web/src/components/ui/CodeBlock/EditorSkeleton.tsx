// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

import Skeleton from "@mui/material/Skeleton";

interface EditorSkeletonProps {
  height: string;
}

export default function EditorSkeleton({ height }: EditorSkeletonProps) {
  return (
    <div
      style={{
        height,
        width: "100%",
        padding: "16px",
        boxSizing: "border-box",
      }}
    >
      <Skeleton variant="text" width="60%" height={20} sx={{ mb: 1 }} />
      <Skeleton variant="text" width="80%" height={20} sx={{ mb: 1 }} />
      <Skeleton variant="text" width="45%" height={20} sx={{ mb: 1 }} />
      <Skeleton variant="text" width="70%" height={20} sx={{ mb: 1 }} />
      <Skeleton variant="text" width="55%" height={20} />
    </div>
  );
}
