from langchain_openai import ChatOpenAI          # 0.2-style import
from langchain_core.prompts import ChatPrompt
from camel_ai import SystemMessage, UserMessage  # camel-ai abstractions

# 1️⃣  pick the LLM you want Camel to steer
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.3)  # uses OPENAI_API_KEY

# 2️⃣  build a vanilla chain
base_prompt = ChatPrompt(
    messages=[
        ("system", "{system_msg}"),
        ("user", "{user_msg}")
    ]
)
chain = base_prompt | llm

# 3️⃣  wrap it in a Camel-AI agent helper
def run_agent(user_msg: str) -> str:
    system_msg = SystemMessage(
        content="You are a helpful assistant that follows Camel role-playing guidelines."
    )
    user_msg = UserMessage(content=user_msg)
    response = chain.invoke({"system_msg": system_msg.content,
                             "user_msg": user_msg.content})
    return response.content
