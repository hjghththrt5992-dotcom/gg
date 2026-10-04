# gg

A minimal search engine MVP.

## Features

- Crawl a webpage
- Build a simple in-memory index
- Search via HTTP

## Install

```bash
npm install
```

## Run

```bash
npm start
```

## Usage

### Crawl a page

```bash
curl -X POST http://localhost:3000/crawl -H "Content-Type: application/json" -d '{"url":"https://example.com"}'
```

### Search

Open in browser:

http://localhost:3000/search?q=example

## Notes

This is a toy search engine. No ranking, no persistence, no distributed crawling.

## Knowledge-base trained model (`llm/`)

Train a small open-source LLM (Qwen2.5 0.5B/1.5B) on your own knowledge base so it answers from memory,
on an ordinary computer without a GPU. Documents are turned into training data (original passages,
paraphrased rewrites, generated Q&A) and learned with LoRA. See [llm/README.md](llm/README.md) (Chinese).

```bash
pip install -r llm/requirements.txt
python llm/main.py check && python llm/main.py download && python llm/main.py auto && python llm/main.py chat
```
