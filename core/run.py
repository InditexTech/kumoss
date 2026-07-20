# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

import uvicorn
from dotenv import load_dotenv

_ = load_dotenv()


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", reload=True)
