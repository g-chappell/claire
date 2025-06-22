# src/backend/agents/agent.py
from langchain_core.prompts import ChatPromptTemplate
from langchain_anthropic import ChatAnthropic 

llm = ChatAnthropic(model="claude-3-haiku-20240307", temperature=0.3)

base_prompt = ChatPromptTemplate.from_messages(
    [("system", "{system_msg}"), ("user", "{user_msg}")]
)
chain = base_prompt | llm


def run_agent(user_msg: str) -> str:
    system_msg = (
        "You are a helpful assistant that follows Camel role-playing guidelines."
    )
    response = chain.invoke({"system_msg": system_msg, "user_msg": user_msg})
    return response.content

