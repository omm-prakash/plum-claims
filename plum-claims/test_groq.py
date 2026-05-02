import os
from dotenv import load_dotenv
load_dotenv()
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage

print("Testing Groq...")
llm = ChatGroq(model="llama3-70b-8192", temperature=0.0, max_retries=1)
try:
    res = llm.invoke([HumanMessage(content="Hello")])
    print("Success:", res.content)
except Exception as e:
    print("Error:", e)
