# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0


from typing import override

from src.shared.constants import SessionStatus


class Status:
    def __init__(self, session_status: SessionStatus, msg: str) -> None:
        """
        Class that defines the Session Status entity
        :param session_status: the status of the session.
        :param msg: The message associated to the status.
        """
        self.__status = session_status
        self.__msg = msg

    @property
    def status(self) -> SessionStatus:
        return self.__status

    @property
    def msg(self) -> str:
        return self.__msg

    @override
    def __str__(self) -> str:
        return f"<Status>{self.status}, {self.msg}"
