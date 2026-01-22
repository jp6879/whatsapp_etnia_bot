from app.state_machines.base import BaseStateMachine


class StateMachineFactory:
    def __init__(self, standard_sm, seasonal_sm, groupal_sm):
        self.standard_sm = standard_sm
        self.seasonal_sm = seasonal_sm
        self.groupal_sm = groupal_sm
        self._mapping = {
            "Aruba": self.seasonal_sm,
            "Turquia": self.standard_sm,
        }

    def get_sm(self, destination: str) -> BaseStateMachine:
        return self._mapping.get(destination, self.standard_sm)
