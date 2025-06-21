from camel.agents import RolePlaying
from camel.configs import ChatAgentConfig
from langchain_openai import ChatOpenAI

# Init LLMs
assistant = ChatOpenAI(model="gpt-4", temperature=0.7)
user = ChatOpenAI(model="gpt-4", temperature=0.3)

# Role descriptions
user_role = "Product Owner"
user_goal = "Define features for a pirate-themed web app."

assistant_role = "Developer"
assistant_goal = "Write Python code for web app features."

# Start a CAMEL roleplay
roleplay = RolePlaying(
    assistant_role_name=assistant_role,
    assistant_agent_kwargs=dict(
        config=ChatAgentConfig(role=assistant_role, goal=assistant_goal)
    ),
    user_role_name=user_role,
    user_agent_kwargs=dict(
        config=ChatAgentConfig(role=user_role, goal=user_goal)
    ),
    assistant_llm=assistant,
    user_llm=user
)

# Run a sample interaction
messages, _ = roleplay.init_chat()
response = roleplay.step()

print("🧠 Assistant:", response.msg.content)
