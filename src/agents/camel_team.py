class DummyRoleplay:
    def step(self):
        class Msg:
            content = "Hello from the dummy roleplay agent (placeholder)."
        return type("Response", (), {"msg": Msg()})()

roleplay = DummyRoleplay()
