import typer
from agents.camel_team import roleplay

app = typer.Typer()

@app.command()
def simulate():
    print("🎭 Running agent simulation...\n")
    response = roleplay.step()
    print("Assistant:", response.msg.content)



