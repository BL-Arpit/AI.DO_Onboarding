# AI.DO onboarding workspace

Owner, HR and Employee use one chat workspace. PostgreSQL stores accounts and employee records. MongoDB stores private conversations and drafts. Qdrant helps find employee records in context. TextCNN classifies prompts locally, with optional GGUF phrasing for generic help.

Start with [deployment and testing](DEPLOYMENT.md). For local startup, install `requirements.lock`, configure the values in a private `.env` using the examples, and run `python run.py`. A local SQLite fallback is available for development. MongoDB is required for conversation history.
