from aiogram.fsm.state import State, StatesGroup


class InteractionState(StatesGroup):
    waiting_parse_url = State()
    waiting_add_username = State()
    waiting_modify_username = State()
    waiting_unsubscribe_username = State()
