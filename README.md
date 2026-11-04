# GuruAI: Context-Aware Adaptive Tutoring System (using RAG)

## Overview
GuruAI (also known as "The Scholar") is an advanced context-aware, adaptive tutoring system powered by Retrieval-Augmented Generation (RAG). It goes beyond traditional chatbots by personalizing the learning experience: building a continuously updating knowledge profile for the user, tracking their topic mastery, retaining their preferences, and providing highly tailored explanations and quizzes.

## Core Features
- **Interactive Study Sessions (RAG)**: Chat naturally with your uploaded documents (PDFs, DOCX). Features an optimized Corrective RAG (CRAG) pipeline with collective relevance filtering to minimize latency and hallucination.
- **Adaptive Knowledge Tracking**: Implements an Exponential Moving Average (EMA) algorithm to track sustained mastery levels across subjects and topics, categorizing your knowledge as *Strong*, *Average*, or *Weak*.
- **Personalized Topic Tutor**: Automatically scales topic explanations and generates difficulty-adjusted quizzes based precisely on your current tracked mastery level.
- **Persistent User Memory**: An embedded memory system extracts and retains your learning preferences, background, and goals to provide deeply contextual interactions across all sessions globally.
- **Session & Multi-user Management**: Supports robust handling of distinct chat sessions, independent vector spaces per session, and multi-tenant capabilities (PostgreSQL, PBKDF2-HMAC-SHA256 password hashing, HMAC-signed session tokens).
- **Modern UI/UX**: Sleek, responsive, full-screen UI with interactive widgets, multi-view navigation, and dynamic dark/light mode toggling built with TailwindCSS.

## Tech Stack
- **Backend Framework**: FastAPI, Python
- **AI & Orchestration**: Langchain
- **Language Models**: Groq (`openai/gpt-oss-120b`) for answers/quizzes; Google Gemini for the CRAG relevance grader
- **Embeddings**: Google Gemini `gemini-embedding-001` (hosted API, 768 dims), via `langchain-google-genai`
- **Vector Database**: PostgreSQL + `pgvector` extension
- **Document Processing**: PyPDF, docx2txt
- **Frontend**: HTML5, Vanilla JavaScript, TailwindCSS

## Setup & Installation

1. **Clone the Repository**
```bash
git clone <repository_url>
cd Context-Aware-Adaptive-Tutoring-System-using-Retrieval-Augmented-Generation-RAG-
```

2. **Create a Virtual Environment**
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`
```

3. **Install Dependencies**
```bash
pip install -r requirements.txt
```

4. **Environment Variables**
Create a `.env` file in the root directory and add your required API keys:
```env
GOOGLE_API_KEY=your_google_api_key
GROQ_API_KEY=your_groq_api_key
JWT_SECRET_KEY=your_jwt_secret
DATABASE_URL=postgresql://guruai:guruai_dev_pw@localhost:5432/guruai_dev
```
`JWT_SECRET_KEY` and `DATABASE_URL` each fall back to a hardcoded local default if
unset, but you should set both explicitly outside of local dev. `DATABASE_URL`
must point at a Postgres instance with the `pgvector` extension available.

5. **Run the Application**
```bash
python server.py
```
*(Alternatively, use Uvicorn directly: `uvicorn server:app --host 0.0.0.0 --port 8000 --reload`)*

6. **Access the Web Interface**
Open your browser and navigate to [http://localhost:8000](http://localhost:8000)

## Directory Structure
- `src/`: Core application logic.
  - `rag/`: Implementation of CRAG, RAG chains, the pgvector-backed embedder, document loaders, and dynamic quiz generation.
  - `personalization/`: Mastery tracker (EMA algorithm) and persistent user memory management.
  - `auth/`: Authentication and multi-user configurations.
- `static/`: Frontend HTML, JavaScript, and styling.
- `server.py`: FastAPI server configuration and API route definitions.

`faiss_index_db/` is a leftover local directory from before the Postgres/pgvector
migration; the app no longer reads or writes it. Chunk embeddings now live in the
`document_chunks` table in PostgreSQL.
