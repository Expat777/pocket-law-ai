"""FSM-состояния диалога (задача MVP 2).

Три состояния по разделу 4:
  - normal_question — обычный вопрос;
  - awaiting_clarification — бот задал уточняющий вопрос и ждёт ответа;
  - uploading_file — идёт приём/обработка файла.

Согласие на обработку ПДн (152-ФЗ) — не FSM-состояние, а флаг пользователя
в хранилище (см. repository.consent_*): переживает рестарт бота, в отличие от FSM.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class Dialog(StatesGroup):
    normal_question = State()
    awaiting_clarification = State()
    uploading_file = State()
