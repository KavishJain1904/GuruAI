from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from pydantic import BaseModel, Field
from typing import List
from src.core.llm import llm_balanced, llm_creative


# ── Adaptive Explanation ──────────────────────────────────────────────────────

EXPLAIN_PROMPT = PromptTemplate(
    template="""You are an intelligent adaptive tutor. A student has asked you to explain the topic "{topic}" under the subject "{subject}".

The student's current mastery level for this topic is: {mastery_level} (score: {score_pct}%).

Adjust your explanation accordingly:
- If mastery is STRONG (>75%): Be terse, crisp, and advanced. Assume the student knows the fundamentals. Focus on nuances, edge cases, and real-world applications. Use technical language comfortably.
- If mastery is AVERAGE (50-75%): Give a balanced explanation. Reinforce core ideas with examples and fill gaps they likely have.
- If mastery is WEAK (<50%): Be thorough and beginner-friendly. Explain from first principles with analogies, simple examples, and key vocabulary definitions. Use a step-by-step approach.

Format your response as valid **Markdown** with:
- A clear heading
- Organized sections using ##
- Bullet points or numbered lists where helpful
- Code blocks if relevant (for CS topics)
- End with 1-2 key takeaways in a "## Key Takeaways" section

Topic: {topic}
Subject: {subject}
Mastery Level: {mastery_level}
""",
    input_variables=["topic", "subject", "mastery_level", "score_pct"],
)


def generate_topic_explanation(topic: str, subject: str, mastery_level: str, score_pct: int) -> str:
    """Generate an adaptive explanation for a topic based on the student's mastery."""
    model = llm_balanced
    chain = EXPLAIN_PROMPT | model | StrOutputParser()
    return chain.invoke({
        "topic": topic,
        "subject": subject,
        "mastery_level": mastery_level,
        "score_pct": score_pct,
    })


# ── Topic-Specific Quiz ───────────────────────────────────────────────────────

class TopicQuizQuestion(BaseModel):
    question: str = Field(description="The question text")
    options: List[str] = Field(description="Exactly 4 options")
    correct_index: int = Field(description="Index of the correct option (0-3)")
    explanation: str = Field(description="Why the answer is correct")


class TopicQuiz(BaseModel):
    questions: List[TopicQuizQuestion] = Field(description="List of 4 quiz questions")


TOPIC_QUIZ_PROMPT = PromptTemplate(
    template="""You are Study AI. Generate 4 high-quality multiple choice quiz questions specifically about "{topic}" in the domain of "{subject}".

Student mastery level: {mastery_level} ({score_pct}%).
- If STRONG: Make questions harder — edge cases, applications, deeper theory.
- If AVERAGE: Mix foundational and intermediate questions.
- If WEAK: Focus on core definitions, basic concepts, and key applications.

{format_instructions}
Do not include markdown outside the JSON block.""",
    input_variables=["topic", "subject", "mastery_level", "score_pct"],
    partial_variables={},
)


def generate_topic_quiz(topic: str, subject: str, mastery_level: str, score_pct: int) -> dict:
    """Generate an adaptive quiz about a specific topic."""
    model = llm_creative
    parser = JsonOutputParser(pydantic_object=TopicQuiz)

    prompt = TOPIC_QUIZ_PROMPT.partial(format_instructions=parser.get_format_instructions())
    chain = prompt | model | parser
    try:
        return chain.invoke({
            "topic": topic,
            "subject": subject,
            "mastery_level": mastery_level,
            "score_pct": score_pct,
        })
    except Exception as e:
        print(f"Error generating topic quiz: {e}")
        return {"questions": []}
